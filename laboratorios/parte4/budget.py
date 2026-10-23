"""Carga limitada no loopback: orçamento simulado, chamadas e morte de worker reais."""
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler

from .common import new_output, write, seal, integrity


class Budget:
    def __init__(self, path, limit):
        self.path, self.limit = Path(path), limit
        if type(limit) is not int or limit <= 0: raise ValueError('limit')
        if not self.path.exists():
            with self.connect() as db:
                db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,tenant TEXT,ceiling INT,state TEXT,charged INT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def reserve(self, job, tenant, ceiling):
        if type(ceiling) is not int or ceiling <= 0 or ceiling > self.limit:
            raise ValueError('ceiling')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT tenant,ceiling FROM jobs WHERE id=?', (job,)).fetchone()
            if old:
                if old != (tenant, ceiling): raise ValueError('id conflict')
                return False
            used = db.execute("SELECT coalesce(sum(CASE WHEN state IN ('reserved','unknown') THEN ceiling ELSE charged END),0) FROM jobs WHERE tenant=?", (tenant,)).fetchone()[0]
            if used + ceiling > self.limit: return False
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', (job, tenant, ceiling, 'reserved', 0))
            return True

    def cancel(self, job, strict=True):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=? WHERE id=? AND state='reserved'",
                       ('unknown' if strict else 'cancelled', job))

    def settle(self, job, charged):
        if type(charged) is not int or charged < 0: raise ValueError('charged')
        with self.connect() as db:
            row = db.execute('SELECT ceiling,state,charged FROM jobs WHERE id=?', (job,)).fetchone()
            if row is None: raise ValueError('unknown job')
            if charged > row[0]: raise ValueError('provider exceeded ceiling')
            if row[1] == 'settled':
                if row[2] != charged: raise ValueError('receipt conflict')
                return
            db.execute("UPDATE jobs SET state='settled',charged=? WHERE id=?", (charged, job))

    def snapshot(self):
        with self.connect() as db:
            rows = [{'id': r[0], 'tenant': r[1], 'ceiling': r[2], 'state': r[3], 'charged': r[4]}
                    for r in db.execute('SELECT * FROM jobs ORDER BY id')]
        return {'jobs': rows, 'charged': sum(r['charged'] for r in rows),
                'held': sum(r['ceiling'] for r in rows if r['state'] in ('reserved','unknown'))}


def input_ceiling(text, steps):
    if not isinstance(text, str) or not 0 < len(text.encode('utf-8')) <= 256:
        raise ValueError('input bytes')
    if type(steps) is not int or not 1 <= steps <= 3: raise ValueError('steps')
    return 1 + steps


def schedule(requests, fair):
    queues = defaultdict(deque); admitted = []; rejected = []
    for request in requests:
        tenant = request['tenant']
        if len(admitted) >= 8 or (fair and len(queues[tenant]) >= 4):
            rejected.append(request); continue
        queues[tenant].append(request); admitted.append(request)
    if not fair: return admitted, rejected
    ordered = []
    while any(queues.values()):
        for tenant in sorted(queues):
            if queues[tenant]: ordered.append(queues[tenant].popleft())
    return ordered, rejected


class Provider(AbstractContextManager):
    def __init__(self, directory, delay=.02):
        self.path = Path(directory); self.path.mkdir()
        self.db = self.path / 'provider.sqlite'; self.delay = delay
        self.lock = threading.Lock(); self.active = 0; self.peak = 0
        self.started = threading.Event(); self.done = threading.Event()
        with sqlite3.connect(self.db) as con:
            con.execute('CREATE TABLE starts(job TEXT PRIMARY KEY,tenant TEXT,started REAL)')
            con.execute('CREATE TABLE receipts(job TEXT PRIMARY KEY,tenant TEXT,charged INT,ended REAL)')

    def __enter__(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 4096: self.send_error(413); return
                data = json.loads(self.rfile.read(size))
                with sqlite3.connect(owner.db) as con:
                    con.execute('INSERT INTO starts VALUES (?,?,?)',
                                (data['job'], data['tenant'], time.perf_counter()))
                with owner.lock:
                    owner.active += 1; owner.peak = max(owner.peak, owner.active)
                owner.started.set()
                time.sleep(owner.delay)
                with sqlite3.connect(owner.db) as con:
                    con.execute('INSERT INTO receipts VALUES (?,?,?,?)',
                                (data['job'], data['tenant'], 3, time.perf_counter()))
                with owner.lock: owner.active -= 1
                owner.done.set()
                raw = b'{"charged":3}'
                try:
                    self.send_response(200); self.send_header('Content-Length', str(len(raw)))
                    self.end_headers(); self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start(); self.url = f'http://127.0.0.1:{self.server.server_port}'
        return self

    def receipts(self):
        with sqlite3.connect(self.db) as db:
            return [{'job':r[0], 'tenant':r[1], 'charged':r[2]} for r in db.execute('SELECT * FROM receipts ORDER BY job')]

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(5)


def call(url, job, tenant):
    if not url.startswith('http://127.0.0.1:'): raise ValueError('local only')
    req = Request(url, data=json.dumps({'job':job, 'tenant':tenant}).encode(),
                  headers={'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(req, timeout=5) as response:
        return json.loads(response.read(1024))


def cancellation(out, strict):
    directory = out / ('strict_cancel' if strict else 'weak_cancel'); directory.mkdir()
    budget = Budget(directory / 'budget.sqlite', 4)
    assert budget.reserve('first', 'alpha', 4)
    with Provider(directory / 'remote', delay=.4) as remote:
        command = [sys.executable, '-m', 'laboratorios.parte4.budget', '--worker', remote.url, 'first']
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            if not remote.started.wait(5): raise RuntimeError('worker did not reach receiver')
            process.terminate(); process.wait(timeout=5)
            budget.cancel('first', strict=strict)
            after_cancel = budget.snapshot()
            second = budget.reserve('second', 'alpha', 4)
            if second: call(remote.url, 'second', 'alpha')
            if not remote.done.wait(5): raise RuntimeError('receipt missing')
            # A resposta local morreu, mas a consequência é consultada no receptor.
            deadline = time.monotonic() + 5
            while len(remote.receipts()) != (2 if second else 1):
                if time.monotonic() > deadline: raise RuntimeError('incomplete receiver')
                time.sleep(.01)
            receipts = remote.receipts()
            for receipt in receipts: budget.settle(receipt['job'], receipt['charged'])
            result = {'strict':strict, 'worker_pid':process.pid, 'worker_exit':process.returncode,
                      'worker_stopped':process.poll() is not None, 'after_cancel':after_cancel,
                      'second_admitted':second, 'receipts':receipts, 'settled':budget.snapshot()}
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
    write(directory / 'result.json', result)
    return result


def run(directory):
    out = new_output(directory)
    # Vinte concorrentes disputam cinco reservas de quatro unidades.
    b = Budget(out / 'race.sqlite', 20); barrier = threading.Barrier(20)
    def reserve(i):
        barrier.wait(timeout=10)
        return b.reserve('race_'+str(i), 'alpha', 4)
    with ThreadPoolExecutor(max_workers=20) as pool:
        race = list(pool.map(reserve, range(20)))
    requests = [{'id':f'A{i:02}', 'tenant':'alpha'} for i in range(20)]
    requests += [{'id':f'B{i:02}', 'tenant':'beta'} for i in range(4)]
    load = []
    for fair in (False, True):
        run_dir = out / ('fair' if fair else 'fifo'); run_dir.mkdir()
        admitted, rejected = schedule(requests, fair)
        ledger = Budget(run_dir / 'budget.sqlite', 32)
        start = time.perf_counter()
        with Provider(run_dir / 'remote') as remote:
            def work(request):
                assert ledger.reserve(request['id'], request['tenant'], 4)
                receipt = call(remote.url, request['id'], request['tenant'])
                ledger.settle(request['id'], receipt['charged'])
                return request['id']
            with ThreadPoolExecutor(max_workers=2) as pool:
                completed = list(pool.map(work, admitted))
            receipts = remote.receipts(); peak = remote.peak
        load.append({'fair':fair, 'admitted':admitted, 'rejected':rejected, 'completed':completed,
                     'receipts':receipts, 'peak_active':peak, 'seconds':time.perf_counter()-start,
                     'settled':ledger.snapshot()})
    cancellations = [cancellation(out, strict) for strict in (False, True)]
    input_checks=[]
    for text,steps in (('consulta',3),('x'*257,1),('consulta',4),('consulta',True)):
        try: observation={'accepted':True,'ceiling':input_ceiling(text,steps)}
        except ValueError as exc: observation={'accepted':False,'error':str(exc)}
        input_checks.append({'bytes':len(text.encode()),'steps':steps,**observation})
    write(out / 'results.json', {'lab':'L16','race_admitted':sum(race),'race':b.snapshot(),
                                'load':load,'cancellations':cancellations,
                                'units':'synthetic, not currency or measured LLM tokens',
                                'input_checks':input_checks})
    seal(out); return verify(out)


def verify(directory):
    out=Path(directory); integrity(out)
    r=json.loads((out/'results.json').read_text(encoding='utf-8'))
    assert [x['accepted'] for x in r['input_checks']]==[True,False,False,False]
    assert r['race_admitted']==5 and r['race']['held']==20
    assert Budget(out/'race.sqlite',20).snapshot()==r['race']
    for run in r['load']:
        folder=out/('fair' if run['fair'] else 'fifo')
        assert len(run['admitted'])==len(run['completed'])==len(run['receipts'])==8
        assert len(run['rejected'])==16 and run['peak_active']<=2
        assert Budget(folder/'budget.sqlite',32).snapshot()==run['settled']
        with sqlite3.connect(folder/'remote/provider.sqlite') as db:
            receipts=[{'job':x[0],'tenant':x[1],'charged':x[2]} for x in db.execute('SELECT * FROM receipts ORDER BY job')]
        assert receipts==run['receipts']
        assert sum(x['tenant']=='beta' for x in receipts)==(4 if run['fair'] else 0)
    for c in r['cancellations']:
        folder=out/('strict_cancel' if c['strict'] else 'weak_cancel')
        assert c['worker_stopped'] and c['worker_exit'] is not None
        assert c['second_admitted'] != c['strict']
        assert Budget(folder/'budget.sqlite',4).snapshot()==c['settled']
        with sqlite3.connect(folder/'remote/provider.sqlite') as db:
            assert sum(x[0] for x in db.execute('SELECT charged FROM receipts'))==c['settled']['charged']
        assert c['settled']['charged']==(3 if c['strict'] else 6)
    return {'lab':'L16','race_admitted':5,'load_requests':48,'load_completed':16,
            'cancelled_workers':2,'post_cancel_charges':[c['settled']['charged'] for c in r['cancellations']]}


if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--worker': call(sys.argv[2],sys.argv[3],'alpha')
    else: raise SystemExit('Use python -m laboratorios.parte4 run L16 --out ...')
