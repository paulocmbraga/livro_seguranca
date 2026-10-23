"""Recurso HTTP local com política sob lock e trilha de leituras efetivas.

Dois perfis deliberadamente fracos e um completo. Não expor na rede pública.
Thread é implementação de servidor, não fronteira de isolamento.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
import jwt
from .identity import ACCOUNTS, Authority

DOCUMENTS = {
    'a1': {'tenant': 'alpha', 'owner': 'ana', 'text': 'CONTRATO_ALPHA_720'},
    'b1': {'tenant': 'beta', 'owner': 'bia', 'text': 'CONTRATO_BETA_945'},
    'a2': {'tenant': 'alpha', 'owner': 'outro', 'text': 'RESTRITO_ALPHA_333'},
}
ROUTES = ('/read', '/export', '/debug')


class State:
    def __init__(self, mode='strict'):
        if mode not in ('strict', 'audience_weak', 'rbac_cache_weak', 'cache_weak'):
            raise ValueError('Perfil desconhecido')
        self.mode = mode; self.authority = Authority()
        self.events = []; self.reads = []; self.cache = {}; self.epoch = 1
        self.grants = {('ana', 'a1'), ('bia', 'b1')}
        self.available = True; self.lock = threading.RLock()

    def revoke_grant(self, subject, resource):
        with self.lock:
            self.grants.discard((subject, resource)); self.epoch += 1

    def decide(self, claims, resource, route):
        if not self.available:
            return 503, 'policy_unavailable'
        if 'read' not in claims['scope'].split():
            return 403, 'scope'
        if self.mode == 'rbac_cache_weak':
            return 200, 'role_only'
        doc = DOCUMENTS[resource]; role = ACCOUNTS[claims['sub']]['role']
        if doc['tenant'] != claims['tenant']:
            return 403, 'tenant'
        if role == 'auditor' and route != '/read':
            return 403, 'operation'
        if role != 'auditor' and (claims['sub'], resource) not in self.grants:
            return 403, 'relation'
        return 200, 'policy'

    def handle(self, route, token, body):
        with self.lock:
            case = body.get('case', 'invalid')
            if not isinstance(case, str) or len(case) > 80:
                case = 'invalid'
            result = {'case': case}; reason = 'malformed'; status = 400
            resource = body.get('resource'); claims = None
            if route not in ROUTES:
                status, reason = 404, 'route'
            else:
                try:
                    claims = self.authority.validate(token, self.mode == 'audience_weak')
                except (jwt.InvalidTokenError, TypeError, ValueError):
                    status, reason = 401, 'credential'
                if claims is not None:
                    if not isinstance(resource, str) or resource not in DOCUMENTS:
                        status, reason = 404, 'resource'
                    else:
                        weak = self.mode in ('rbac_cache_weak', 'cache_weak')
                        key = resource if weak else (
                            claims['sub'], claims['tenant'], resource, route, self.epoch)
                        # Variante ruim consulta cache ANTES de autorizar.
                        if weak and key in self.cache:
                            status, reason = 200, 'cache_before_policy'
                        else:
                            status, reason = self.decide(claims, resource, route)
                        if status == 200:
                            hit = key in self.cache
                            if not hit:
                                self.cache[key] = DOCUMENTS[resource]['text']
                            result.update(text=self.cache[key], cache_hit=hit)
                            self.reads.append(dict(case=case, sub=claims['sub'],
                                tenant=claims['tenant'], resource=resource,
                                resource_tenant=DOCUMENTS[resource]['tenant'],
                                route=route, text=result['text'], cache_hit=hit))
            event = dict(case=case, status=status, reason=reason,
                         epoch=self.epoch, route=route)
            self.events.append(event); result['reason'] = reason
            return status, result


@contextmanager
def server(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('size')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('body')
                auth = self.headers.get('Authorization', '')
                token = auth[7:] if auth.startswith('Bearer ') else ''
                status, result = state.handle(self.path, token, body)
            except (ValueError, TypeError):
                status, result = 400, {'reason': 'malformed'}
            payload = json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers(); self.wfile.write(payload)

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}'
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError('Servidor não encerrou')


def call(url, token, case, resource='a1', route='/read', **extra):
    if not url.startswith('http://127.0.0.1:'):
        raise ValueError('Somente bancada local')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url + route, json.dumps(dict(case=case, resource=resource, **extra)).encode(),
                      {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    start = time.perf_counter()
    try:
        response = opener.open(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        result = dict(case=case, status=response.code,
                      body=json.loads(response.read(10000)),
                      elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
    return result
