"""HTTP local real; proposta preparada substitui a geração de um agente.

Não é servidor de produção. Perfil selecionado somente pelo harness no host.
O adversário altera o documento/proposta, nunca credenciais nem perfil.
"""
from contextlib import contextmanager, closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
from pathlib import Path
import socket
import sqlite3
import threading
import time
import unicodedata

from .common import canonical, digest

PROFILES = ('weak', 'filter', 'bound', 'no_owner', 'no_destination')
TOKENS = {'demo-alpha': 'alpha', 'demo-beta': 'beta'}


def normalize(text):
    return unicodedata.normalize('NFKC', text).casefold().strip()


def authorize(profile, actor, proposal):
    if profile not in PROFILES:
        raise ValueError('unknown profile')
    if actor not in ('alpha', 'beta'):
        return False, 'identity'
    owner = normalize(proposal.get('owner', ''))
    destination = normalize(proposal.get('destination', ''))
    if owner not in ('alpha', 'beta') or destination not in ('internal', 'external'):
        return False, 'schema'
    if profile == 'filter' and any(w in proposal.get('text', '').casefold()
                                   for w in ('exportar', 'segredo')):
        return False, 'lexical'
    if profile in ('bound', 'no_destination') and owner != actor:
        return False, 'owner'
    if profile in ('bound', 'no_owner') and destination != 'internal':
        return False, 'destination'
    return True, 'allow'


def effects(db):
    with closing(sqlite3.connect(db)) as c:
        c.row_factory = sqlite3.Row
        return [dict(row) for row in c.execute('SELECT * FROM receipts ORDER BY id')]


@contextmanager
def service(db, profile):
    db = Path(db)
    if db.exists():
        raise FileExistsError(db)
    if profile not in PROFILES:
        raise ValueError(profile)
    with closing(sqlite3.connect(db)) as c, c:
        c.execute('CREATE TABLE records(owner TEXT PRIMARY KEY, payload TEXT)')
        c.executemany('INSERT INTO records VALUES(?,?)',
                      [('alpha','SYNTHETIC_ALPHA_RECORD'),('beta','SYNTHETIC_BETA_RECORD')])
        c.execute('CREATE TABLE receipts(id TEXT PRIMARY KEY, actor TEXT, owner TEXT, destination TEXT, payload_hash TEXT, payload TEXT)')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = canonical(body)
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # efeito já confirmado pode sobreviver à perda da resposta

        def do_GET(self):
            if self.path != '/health':
                return self.reply(404, {})
            self.reply(200, {'profile': profile, 'version': 'p8.1'})

        def do_POST(self):
            if self.path != '/execute':
                return self.reply(404, {})
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                return self.reply(413, {})
            actor = TOKENS.get(self.headers.get('Authorization', '').removeprefix('Bearer '))
            if actor is None:
                return self.reply(401, {'decision': 'identity'})
            try:
                p = json.loads(self.rfile.read(size))
                if not isinstance(p, dict) or not isinstance(p.get('id'), str):
                    raise ValueError('schema')
                allowed, reason = authorize(profile, actor, p)
            except (ValueError, TypeError, AttributeError):
                return self.reply(400, {'decision': 'schema'})
            if not allowed:
                return self.reply(403, {'decision': reason, 'text': 'recusado'})
            owner = normalize(p['owner']); destination = normalize(p['destination'])
            with closing(sqlite3.connect(db)) as c, c:
                payload = c.execute('SELECT payload FROM records WHERE owner=?',(owner,)).fetchone()[0]
                row = (p['id'], actor, owner, destination, digest(payload), payload)
                old = c.execute('SELECT * FROM receipts WHERE id=?', (p['id'],)).fetchone()
                if old and old != row:
                    return self.reply(409, {'decision': 'id_conflict'})
                c.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?,?,?,?)', row)
            # Injeção de falha controlada pelo harness, explicitada nos casos.
            if p.get('fault') == 'lost_reply':
                time.sleep(.08)
            self.reply(200, {'decision': 'allow', 'text': p.get('display', 'concluído')})
    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02})
    worker.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=3)
        if worker.is_alive():
            raise RuntimeError('HTTP worker not closed')


def call(url, proposal, token='demo-alpha', timeout=2):
    start = time.perf_counter()
    request = Request(url + '/execute', data=canonical(proposal),
                      headers={'Authorization': 'Bearer ' + token,
                               'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            status, body = response.status, json.load(response)
    except HTTPError as e:
        status, body = e.code, json.load(e)
    except (TimeoutError, socket.timeout, URLError):
        status, body = None, {'decision': 'unknown'}
    return {'status': status, 'body': body, 'elapsed_seconds': time.perf_counter() - start}
