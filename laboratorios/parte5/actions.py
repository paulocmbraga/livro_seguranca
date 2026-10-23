"""L17: aprovação persistida, efeito HTTP, falha após commit e compensação."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from laboratorios.m1.protocols import Server
from .common import database, new_output, write, seal, integrity


FIELDS = {'operation', 'plan', 'revision', 'resource', 'resource_version',
          'destination', 'policy_version', 'body'}


def fingerprint(action):
    if set(action) != FIELDS or any(not isinstance(v, str) or not v for v in action.values()):
        raise ValueError('contrato da ação')
    return hashlib.sha256(json.dumps(action, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def action(operation='op1'):
    return dict(operation=operation, plan='plan_alpha', revision='1', resource='alpha_contract',
                resource_version='1', destination='portal_alpha', policy_version='1',
                body='AVISO_SINTETICO_ALPHA')


class Domain:
    def __init__(self, path, strict=True):
        self.path, self.strict = Path(path), strict
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS approvals(id PRIMARY KEY,actor,digest,expires);
CREATE TABLE IF NOT EXISTS objects(id PRIMARY KEY,version);
CREATE TABLE IF NOT EXISTS policy(id PRIMARY KEY,version);
CREATE TABLE IF NOT EXISTS operations(id PRIMARY KEY,digest,receipt);
CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY,operation,actor,resource,destination,body,retracted DEFAULT 0);
CREATE TABLE IF NOT EXISTS compensations(receipt PRIMARY KEY,actor,reason);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,operation,allowed,reason,receipt);
INSERT OR IGNORE INTO objects VALUES('alpha_contract','1'),('alpha_annex','1');
INSERT OR IGNORE INTO policy VALUES('current','1');''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def permitted(a, actor):
        return (actor == 'alpha' and a['resource'] in ('alpha_contract', 'alpha_annex')
                and a['destination'] in ('portal_alpha', 'portal_backup'))

    def approve(self, a, actor='alpha', ttl=60):
        digest = fingerprint(a)
        if not self.permitted(a, actor):
            raise PermissionError('política de aprovação')
        identifier = uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO approvals VALUES(?,?,?,?)', (identifier, actor, digest, time.time()+ttl))
        return identifier

    def execute(self, a, grant, actor):
        digest = fingerprint(a)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            approved = db.execute('SELECT actor,digest,expires FROM approvals WHERE id=?', (grant,)).fetchone()
            reason, receipt = 'allowed', None
            if not approved or approved[0] != actor or approved[2] <= time.time():
                reason = 'approval_identity_or_expiry'
            elif not self.permitted(a, actor):
                reason = 'domain_policy'
            elif self.strict and approved[1] != digest:
                reason = 'approval_binding'
            elif self.strict and (db.execute('SELECT version FROM objects WHERE id=?', (a['resource'],)).fetchone()[0]
                                  != a['resource_version'] or db.execute('SELECT version FROM policy').fetchone()[0]
                                  != a['policy_version']):
                reason = 'state_changed'
            previous = db.execute('SELECT digest,receipt FROM operations WHERE id=?', (a['operation'],)).fetchone()
            if reason == 'allowed' and self.strict and previous:
                if previous[0] != digest:
                    reason = 'idempotency_conflict'
                else:
                    reason, receipt = 'replayed', previous[1]
            if reason == 'allowed':
                receipt = db.execute('INSERT INTO receipts(operation,actor,resource,destination,body) VALUES(?,?,?,?,?)',
                    (a['operation'], actor, a['resource'], a['destination'], a['body'])).lastrowid
                db.execute('INSERT OR IGNORE INTO operations VALUES(?,?,?)', (a['operation'], digest, receipt))
            allowed = reason in ('allowed', 'replayed')
            db.execute('INSERT INTO events(operation,allowed,reason,receipt) VALUES(?,?,?,?)',
                       (a['operation'], int(allowed), reason, receipt))
        return {'allowed': allowed, 'reason': reason, 'receipt': receipt}

    def compensate(self, receipt, actor):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT actor FROM receipts WHERE id=?', (receipt,)).fetchone()
            if not row or actor != row[0]:
                return False
            db.execute('INSERT OR IGNORE INTO compensations VALUES(?,?,?)', (receipt, actor, 'retração sintética'))
            db.execute('UPDATE receipts SET retracted=1 WHERE id=?', (receipt,))
        return True

    def app(self, clients):
        async def execute(request):
            actor = clients.get(request.headers.get('authorization', '').removeprefix('Bearer '))
            if actor is None:
                return JSONResponse({'error': 'identity'}, 401)
            data = await request.json()
            if request.url.path == '/compensate':
                ok = self.compensate(data['receipt'], actor)
                return JSONResponse({'compensated': ok}, 200 if ok else 403)
            result = self.execute(data['action'], data['approval'], actor)
            # Falha de resposta provocada DEPOIS do commit; efeito consultável no banco.
            if data.get('fail_after_commit') and result['allowed']:
                return JSONResponse({'error': 'response_failed_after_commit'}, 503)
            return JSONResponse(result, 200 if result['allowed'] else 403)
        return Starlette(routes=[Route('/execute', execute, methods=['POST']),
                                 Route('/compensate', execute, methods=['POST'])])


def run(directory):
    out = new_output(directory); rows = []
    for profile in ('weak', 'strict'):
        domain = Domain(out/(profile+'.sqlite'), profile == 'strict')
        credentials = {secrets.token_urlsafe(24): 'alpha', secrets.token_urlsafe(24): 'beta'}
        bearer = {v: k for k, v in credentials.items()}
        server = Server().start(domain.app(credentials))
        try:
            with httpx.Client(base_url=server.url, timeout=10, trust_env=False) as client:
                def send(label, a, approval, actor='alpha', fail=False):
                    response = client.post('/execute', json={'action': a, 'approval': approval, 'fail_after_commit': fail},
                                           headers={'Authorization': 'Bearer '+bearer[actor]})
                    rows.append({'profile': profile, 'case': label, 'action': a.copy(), 'actor': actor,
                                 'status': response.status_code, 'response': response.json()})
                    return response
                for case in ('legitimate', 'resource', 'destination', 'body', 'replan',
                             'resource_changed', 'policy_changed', 'expired', 'wrong_actor', 'missing'):
                    with domain.db() as db:
                        db.execute("UPDATE objects SET version='1'"); db.execute("UPDATE policy SET version='1'")
                    a = action(case); grant = domain.approve(a, ttl=-1 if case == 'expired' else 60)
                    if case in ('resource', 'destination', 'body', 'replan'):
                        key, value = {'resource': ('resource', 'alpha_annex'), 'destination': ('destination', 'portal_backup'),
                                      'body': ('body', 'CONTEUDO_TROCADO'), 'replan': ('revision', '2')}[case]
                        a[key] = value
                    if case in ('resource_changed', 'policy_changed'):
                        with domain.db() as db:
                            db.execute("UPDATE "+('objects' if case == 'resource_changed' else 'policy')+" SET version='2'")
                    send(case, a, 'inexistente' if case == 'missing' else grant, 'beta' if case == 'wrong_actor' else 'alpha')
                with domain.db() as db:
                    db.execute("UPDATE objects SET version='1'"); db.execute("UPDATE policy SET version='1'")
                a = action('commit_failure'); grant = domain.approve(a)
                send('commit_failure', a, grant, fail=True)
                repeat = send('retry', a, grant)
                changed = {**a, 'body': 'OUTRA_ACAO_MESMO_ID'}
                # Aprovação nova é válida; ID existente continua vinculado ao objeto anterior.
                send('conflicting_retry', changed, domain.approve(changed))
                receipt = repeat.json()['receipt']
                for n in range(2):
                    r = client.post('/compensate', json={'receipt': receipt},
                                    headers={'Authorization': 'Bearer '+bearer['alpha']})
                    rows.append({'profile': profile, 'case': 'compensate_'+str(n), 'receipt': receipt,
                                 'status': r.status_code, 'response': r.json()})
        finally:
            server.close()
    write(out/'results.json', {'lab': 'L17', 'rows': rows, 'reviewer_is_fixture': True,
                               'fault': 'HTTP 503 after committed receipt; not process crash'})
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory); integrity(out)
    r = json.loads((out/'results.json').read_text(encoding='utf-8')); rows = r['rows']
    assert len(rows) == 30 and len({(x['profile'], x['case']) for x in rows}) == 30
    totals = {}
    for profile, expected in [('weak', 10), ('strict', 2)]:
        selected = [x for x in rows if x['profile'] == profile]
        with database(out/(profile+'.sqlite')) as db:
            receipts = db.execute('SELECT id,operation,actor,resource,destination,body,retracted FROM receipts').fetchall()
            events = db.execute('SELECT operation,allowed,reason,receipt FROM events ORDER BY id').fetchall()
            assert len(receipts) == expected and len(events) == 13
            assert db.execute('SELECT count(*) FROM compensations').fetchone()[0] == 1
            assert sum(x[-1] for x in receipts) == 1  # retração não remove história
            attempts = [x for x in selected if 'action' in x]
            for attempt, event in zip(attempts, events, strict=True):
                assert attempt['action']['operation'] == event[0]
                if attempt['case'] == 'commit_failure':
                    assert attempt['status'] == 503 and event[1] == 1
                else:
                    assert (attempt['status'] == 200) == bool(event[1])
                    assert attempt['response']['receipt'] == event[3]
                if event[1]:
                    assert event[3] in {x[0] for x in receipts}
            totals[profile] = len(receipts)
    assert next(x for x in rows if x['profile']=='strict' and x['case']=='retry')['response']['reason']=='replayed'
    assert next(x for x in rows if x['profile']=='strict' and x['case']=='conflicting_retry')['response']['reason']=='idempotency_conflict'
    return {'lab': 'L17', 'http_calls': 30, 'receipts': totals, 'compensations': 2, 'passed': True}
