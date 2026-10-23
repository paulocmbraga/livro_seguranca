"""L18: capacidades JWT atenuadas, introspecção em cadeia e serviço final HTTP.

O endpoint /delegate é um contrato didático próprio, não uma implementação RFC 8693.
"""
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from laboratorios.m1.protocols import Server
from .common import database, new_output, write, seal, integrity


class Authority:
    def __init__(self, path, issuer):
        self.path, self.issuer = Path(path), issuer
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.clients = {secrets.token_urlsafe(24): s for s in ('broker', 'reader', 'analyzer', 'domain')}
        with self.db() as db:
            db.executescript('CREATE TABLE issued(jti PRIMARY KEY,parent,claims,revoked DEFAULT 0);'
                             'CREATE TABLE audit(id INTEGER PRIMARY KEY,operation,actor,allowed,reason,jti);')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue(self, **overrides):
        claims = {'iss': self.issuer, 'sub': 'user_alpha', 'tenant': 'alpha', 'act': 'broker',
                  'aud': 'broker', 'scope': ['read'], 'resources': ['alpha_contract'],
                  'targets': ['domain'], 'actors': ['reader', 'analyzer'], 'depth': 2,
                  'iat': int(time.time()), 'exp': int(time.time())+120, 'jti': uuid.uuid4().hex, 'parent': None}
        claims.update(overrides)
        token = jwt.encode(claims, self.key, algorithm='RS256')
        with self.db() as db:
            db.execute('INSERT INTO issued(jti,parent,claims) VALUES(?,?,?)',
                       (claims['jti'], claims['parent'], json.dumps(claims, sort_keys=True)))
        return token

    def validate(self, token, audience=None):
        claims = jwt.decode(token, self.key.public_key(), algorithms=['RS256'], issuer=self.issuer,
                            audience=audience, options={'verify_aud': audience is not None,
                            'require': ['iss', 'sub', 'tenant', 'aud', 'exp', 'iat', 'jti', 'act']})
        with self.db() as db:
            current, visited = claims['jti'], set()
            while current is not None:
                if current in visited or len(visited) > 3:
                    raise jwt.InvalidTokenError('chain')
                visited.add(current)
                row = db.execute('SELECT parent,claims,revoked FROM issued WHERE jti=?', (current,)).fetchone()
                if not row or row[2]:
                    raise jwt.InvalidTokenError('revoked_or_unknown')
                saved = json.loads(row[1])
                if saved['exp'] <= time.time():
                    raise jwt.ExpiredSignatureError('ancestor_expired')
                if current == claims['jti'] and saved != claims:
                    raise jwt.InvalidTokenError('issued_claims_mismatch')
                current = row[0]
        return claims

    def delegate(self, token, actor, target, scope, resources, next_actor, ttl=60):
        parent = self.validate(token)
        if (parent['act'] != actor or parent['depth'] <= 0 or target not in parent['targets']
            or next_actor not in parent['actors'] or not scope or not resources
            or not set(scope) <= set(parent['scope']) or not set(resources) <= set(parent['resources'])):
            raise PermissionError('attenuation')
        return self.issue(sub=parent['sub'], tenant=parent['tenant'], act=next_actor, aud=target,
                          scope=scope, resources=resources, targets=parent['targets'], actors=parent['actors'],
                          depth=parent['depth']-1, parent=parent['jti'],
                          exp=min(parent['exp'], int(time.time())+ttl))

    def revoke(self, jti):
        with self.db() as db:
            db.execute('UPDATE issued SET revoked=1 WHERE jti=?', (jti,))

    def app(self):
        async def endpoint(request):
            actor = self.clients.get(request.headers.get('authorization', '').removeprefix('Bearer '))
            if actor is None:
                return JSONResponse({'error': 'workload_identity'}, 401)
            body = await request.json(); result, status, identifier = {}, 200, None
            try:
                if request.url.path == '/delegate':
                    token = self.delegate(body['parent_token'], actor, body['target'], body['scope'],
                                          body['resources'], body['next_actor'])
                    identifier = self.validate(token)['jti']; result = {'access_token': token}
                elif actor == 'domain':
                    claims = self.validate(body['token'], 'domain'); identifier = claims['jti']
                    result = {'active': True, 'claims': claims}
                else:
                    raise PermissionError('introspection_client')
            except (PermissionError, jwt.InvalidTokenError) as error:
                status, result = 403, {'error': type(error).__name__}
            with self.db() as db:
                db.execute('INSERT INTO audit(operation,actor,allowed,reason,jti) VALUES(?,?,?,?,?)',
                           (request.url.path, actor, status == 200, result.get('error', 'ok'), identifier))
            return JSONResponse(result, status, headers={'Cache-Control': 'no-store'})
        return Starlette(routes=[Route('/delegate', endpoint, methods=['POST']),
                                 Route('/introspect', endpoint, methods=['POST'])])


class Consumer:
    def __init__(self, path, issuer_url, domain_credential):
        self.path, self.issuer_url, self.credential = Path(path), issuer_url, domain_credential
        with database(path) as db:
            db.executescript('CREATE TABLE receipts(id INTEGER PRIMARY KEY,case_id,profile,operation,resource,actor);'
                             'CREATE TABLE attempts(id INTEGER PRIMARY KEY,case_id,profile,allowed,reason);')

    def app(self):
        async def operate(request):
            body = await request.json(); token = request.headers.get('authorization', '').removeprefix('Bearer ')
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                auth = await client.post(self.issuer_url+'/introspect', json={'token': token},
                                        headers={'Authorization': 'Bearer '+self.credential})
            allowed, reason, actor = False, 'credential', None
            if auth.status_code == 200:
                claims = auth.json()['claims']; actor = claims['act']
                # Controle negativo: deputy usa sua permissão administrativa, ignorando a atenuação.
                allowed = (body['profile'] == 'weak' or
                           (body['operation'] in claims['scope'] and body['resource'] in claims['resources']))
                reason = 'allowed' if allowed else 'capability'
            with database(self.path) as db:
                db.execute('INSERT INTO attempts(case_id,profile,allowed,reason) VALUES(?,?,?,?)',
                           (body['case'], body['profile'], int(allowed), reason))
                if allowed:
                    db.execute('INSERT INTO receipts(case_id,profile,operation,resource,actor) VALUES(?,?,?,?,?)',
                               (body['case'], body['profile'], body['operation'], body['resource'], actor))
            return JSONResponse({'allowed': allowed, 'reason': reason}, 200 if allowed else 403)
        return Starlette(routes=[Route('/operate', operate, methods=['POST'])])


def run(directory):
    out = new_output(directory); rows, issuance = [], []
    with ExitStack() as stack:
        issuer, service = Server(), Server()
        authority = Authority(out/'authority.sqlite', issuer.url)
        creds = {v: k for k, v in authority.clients.items()}
        issuer.start(authority.app()); stack.callback(issuer.close)
        service.start(Consumer(out/'consumer.sqlite', issuer.url, creds['domain']).app()); stack.callback(service.close)
        root = authority.issue()
        with httpx.Client(timeout=10, trust_env=False) as wire:
            def delegate(label, parent=root, actor='broker', **changes):
                payload = dict(parent_token=parent, target='domain', scope=['read'], resources=['alpha_contract'], next_actor='reader')
                payload.update(changes)
                r = wire.post(issuer.url+'/delegate', json=payload, headers={'Authorization': 'Bearer '+creds[actor]})
                issuance.append({'case': label, 'status': r.status_code, 'token_present': 'access_token' in r.json()})
                return r.json().get('access_token')
            child = delegate('attenuated')
            grandchild = delegate('second_hop', child, 'reader', next_actor='analyzer')
            for label, change in [('scope_escalation', {'scope': ['write']}), ('foreign_resource', {'resources': ['beta_contract']}),
                                  ('foreign_audience', {'target': 'other'}), ('wrong_actor', {'actor': 'analyzer'})]:
                delegate(label, **change)
            delegate('depth_exhausted', grandchild, 'analyzer')
            write(out/'public_key.json', json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(authority.key.public_key())))
            write(out/'claims.json', {'root': authority.validate(root), 'child': authority.validate(child),
                                      'grandchild': authority.validate(grandchild)})
            def call(label, token, operation='read', resource='alpha_contract'):
                for profile in ('weak', 'strict'):
                    r = wire.post(service.url+'/operate', json={'case': label, 'profile': profile,
                        'operation': operation, 'resource': resource, 'role': 'administrator', 'tenant': 'beta'},
                        headers={'Authorization': 'Bearer '+token})
                    rows.append({'case': label, 'profile': profile, 'status': r.status_code, 'response': r.json()})
            call('legitimate', child); call('write', child, 'write'); call('foreign_read', child, resource='beta_contract')
            call('grandchild', grandchild)
            call('wrong_audience', root)
            expired = authority.issue(act='reader', aud='domain', exp=int(time.time())-1)
            call('expired', expired)
            call('signature', child.rsplit('.', 1)[0]+'.'+'A'*342)
            authority.revoke(authority.validate(root)['jti'])
            call('revoked_child', child); call('revoked_grandchild', grandchild)
    write(out/'results.json', {'lab': 'L18', 'issuance': issuance, 'rows': rows,
        'issuer': issuer.url, 'contract': 'custom capability delegation; not RFC8693 implementation',
        'revocation': 'live local chain introspection before operation; no distributed atomicity'})
    seal(out); return verify(out)


def verify(directory):
    out=Path(directory); integrity(out); r=json.loads((out/'results.json').read_text(encoding='utf-8'))
    assert len(r['rows'])==18 and len({(x['case'],x['profile']) for x in r['rows']})==18
    assert len(r['issuance'])==7 and sum(x['token_present'] for x in r['issuance'])==2
    with database(out/'consumer.sqlite') as db:
        receipts=db.execute('SELECT case_id,profile,operation,resource,actor FROM receipts').fetchall()
        attempts=db.execute('SELECT case_id,profile,allowed FROM attempts ORDER BY id').fetchall()
    assert len(receipts)==6 and len(attempts)==18
    for row, event in zip(r['rows'],attempts,strict=True):
        assert (row['case'],row['profile'])==event[:2]
        expected=row['case'] in ('legitimate','grandchild') or (row['profile']=='weak' and row['case'] in ('write','foreign_read'))
        assert (row['status']==200)==bool(event[2])==expected
        assert sum(x[0]==row['case'] and x[1]==row['profile'] for x in receipts)==int(expected)
    claims=json.loads((out/'claims.json').read_text(encoding='utf-8'))
    assert claims['grandchild']['parent']==claims['child']['jti'] and claims['child']['parent']==claims['root']['jti']
    assert claims['child']['exp']<=claims['root']['exp'] and claims['grandchild']['depth']==0
    with database(out/'authority.sqlite') as db:
        assert db.execute('SELECT revoked FROM issued WHERE jti=?',(claims['root']['jti'],)).fetchone()==(1,)
        assert db.execute('SELECT count(*) FROM audit').fetchone()[0]==25
    return {'lab':'L18','delegation_requests':7,'domain_requests':18,'introspections':18,
            'receipts':{'weak':4,'strict':2},'passed':True}
