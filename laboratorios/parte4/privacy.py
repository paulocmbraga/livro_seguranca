"""Rastreamento sintético em gateway e receptor HTTP, sem provedor pago ou LLM."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import threading
from urllib.request import Request, build_opener, ProxyHandler

from .common import new_output, write, seal, integrity

EMAIL = 'canary-l15@example.test'
NOTE = 'PRIVATE_NOTE_CANARY_L15'


def transform(profile, record):
    if profile == 'minimize':
        return {k: record[k] for k in ('topic', 'amount')}
    raw = json.dumps(record, ensure_ascii=False)
    if profile == 'redact':
        raw = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', raw)
    if profile == 'tokenize':
        raw = raw.replace(EMAIL, 'TOKEN_L15_CUSTOMER')
    return json.loads(raw)


def authorize_route(purpose, provider):
    return purpose == 'estimate' and provider == 'approved_local'


@contextmanager
def provider(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE received(id TEXT PRIMARY KEY,payload TEXT,response TEXT)')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192:
                self.send_error(413); return
            data = json.loads(self.rfile.read(size))
            answer = {'total': data['payload']['amount'] + 5, 'echo': data['payload']}
            with sqlite3.connect(path) as db:
                db.execute('INSERT INTO received VALUES (?,?,?)',
                           (data['id'], json.dumps(data['payload']), json.dumps(answer)))
            raw = json.dumps(answer).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); t.join(3)


def count_markers(value):
    raw = json.dumps(value, ensure_ascii=False)
    return {'email': raw.count(EMAIL), 'note': raw.count(NOTE)}


def run(directory):
    out = new_output(directory); rows = []; components = []
    with sqlite3.connect(out / 'local.sqlite') as local:
        local.executescript('CREATE TABLE cache(id TEXT PRIMARY KEY,data TEXT);'
                            'CREATE TABLE vault(token TEXT PRIMARY KEY,value TEXT);'
                            'CREATE TABLE audit(id TEXT,data TEXT);')
        with provider(out / 'provider.sqlite') as url:
            opener = build_opener(ProxyHandler({}))
            for profile in ('late', 'redact', 'tokenize', 'minimize'):
                for hidden in (False, True):
                    identifier = profile + ('_note' if hidden else '_basic')
                    record = {'topic': 'invoice', 'amount': 50, 'email': EMAIL,
                              'customer_ref': 'LOCAL_C17', 'note': NOTE if hidden else 'standard'}
                    payload = transform(profile, record)
                    assert authorize_route('estimate', 'approved_local')
                    local.execute('INSERT OR REPLACE INTO vault VALUES (?,?)', ('TOKEN_L15_CUSTOMER', EMAIL)) if profile == 'tokenize' else None
                    request = Request(url, data=json.dumps({'id': identifier, 'payload': payload}).encode(),
                                      headers={'Content-Type': 'application/json'})
                    with opener.open(request, timeout=3) as response:
                        answer = json.loads(response.read(8192))
                    # Projeção tardia sempre retira o eco da resposta visível.
                    visible = {'total': answer['total']}
                    cache = answer if profile != 'minimize' else visible
                    tool = payload if profile != 'minimize' else {'customer_ref': 'LOCAL_C17', 'total': answer['total']}
                    audit = {'id': identifier, 'profile': profile, 'status': 'ok'} if profile == 'minimize' else {'id': identifier, 'input': record, 'output': answer}
                    local.execute('INSERT INTO cache VALUES (?,?)', (identifier, json.dumps(cache)))
                    local.execute('INSERT INTO audit VALUES (?,?)', (identifier, json.dumps(audit)))
                    observed = {'context': record, 'gateway': payload, 'provider': payload,
                                'cache': cache, 'tool': tool, 'audit': audit, 'user': visible}
                    components.append({'id': identifier, 'components': observed})
                    rows.append({'id': identifier, 'profile': profile, 'hidden_note': hidden,
                                 'utility_total': visible['total'], 'exposure': {k: count_markers(v) for k,v in observed.items()}})
            # Outra rota é recusada antes de qualquer POST; receptor é o oráculo.
            denied = not authorize_route('estimate', 'unapproved')
        local.commit()
        before = {'cache': local.execute('SELECT count(*) FROM cache').fetchone()[0],
                  'audit': local.execute('SELECT count(*) FROM audit').fetchone()[0],
                  'vault': local.execute('SELECT count(*) FROM vault').fetchone()[0]}
        # Limpa cópias operacionais específicas, conservando auditoria declarada.
        local.execute('DELETE FROM cache'); local.execute('DELETE FROM vault'); local.commit()
        after = {table: local.execute('SELECT count(*) FROM '+table).fetchone()[0]
                 for table in ('cache', 'audit', 'vault')}
    with sqlite3.connect(out / 'provider.sqlite') as db:
        received = [{'id': x[0], 'payload': json.loads(x[1]), 'response': json.loads(x[2])}
                    for x in db.execute('SELECT * FROM received ORDER BY rowid')]
        db.execute('DELETE FROM received'); db.commit()
        provider_after = db.execute('SELECT count(*) FROM received').fetchone()[0]
    write(out / 'provider_before_cleanup.json', received)
    write(out / 'components.json', components)
    write(out / 'results.json', {'lab': 'L15', 'rows': rows, 'denied_route': denied,
        'provider_calls': len(received), 'before_cleanup': before, 'after_cleanup': after,
        'provider_after_cleanup': provider_after, 'synthetic_evidence_retained': True,
        'provider_is_local_stub': True, 'llm_generation': False})
    seal(out); return verify(out)


def verify(directory):
    out = Path(directory); integrity(out)
    r = json.loads((out / 'results.json').read_text(encoding='utf-8'))
    c = json.loads((out / 'components.json').read_text(encoding='utf-8'))
    receipts = json.loads((out / 'provider_before_cleanup.json').read_text(encoding='utf-8'))
    assert len(r['rows']) == len(c) == len(receipts) == r['provider_calls'] == 8
    assert len({row['id'] for row in r['rows']}) == 8
    for row, comp, receipt in zip(r['rows'], c, receipts):
        assert row['id'] == comp['id'] == receipt['id']
        assert row['exposure'] == {k: count_markers(v) for k,v in comp['components'].items()}
        assert receipt['payload'] == comp['components']['provider']
        assert row['utility_total'] == receipt['response']['total'] == 55
        assert not any(row['exposure']['user'].values())
        if row['profile'] == 'minimize':
            assert not any(v for k,m in row['exposure'].items() if k != 'context' for v in m.values())
    with sqlite3.connect(out / 'local.sqlite') as db:
        assert r['after_cleanup'] == {t: db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('cache','audit','vault')}
    with sqlite3.connect(out / 'provider.sqlite') as db:
        assert db.execute('SELECT count(*) FROM received').fetchone()[0] == r['provider_after_cleanup'] == 0
    assert r['denied_route']
    return {'lab': 'L15', 'provider_calls': 8, 'utility_preserved': 8,
            'after_cleanup': r['after_cleanup'], 'evidence_is_not_erased': True}
