"""Consumidores reais em diretório sintético e destinos exclusivamente locais."""
from contextlib import contextmanager, closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError

from .common import new_output, write, seal, integrity, sha


def query(db, tenant, title, strict):
    if strict:
        return db.execute('SELECT id,tenant,text FROM docs WHERE tenant=? AND title=?',
                          (tenant, title)).fetchall()
    return db.execute(f"SELECT id,tenant,text FROM docs WHERE tenant='{tenant}' AND title='{title}'").fetchall()


def safe_path(root, relative):
    root = Path(root).resolve()
    if Path(relative).is_absolute():
        raise ValueError('absolute path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('outside root or missing')
    # O modelo de ameaça não inclui quem altera o filesystem durante open().
    return path


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


@contextmanager
def url_service(directory):
    db = directory / 'url_receipts.sqlite'
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE requests(path TEXT)')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            with sqlite3.connect(db) as con:
                con.execute('INSERT INTO requests VALUES (?)', (self.path,))
            if self.path == '/redirect':
                self.send_response(302)
                self.send_header('Location', '/internal')
                self.end_headers(); return
            data = b'INTERNAL_CANARY_L14' if self.path == '/internal' else b'PUBLIC_DOC_L14'
            self.send_response(200); self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); t.join(3)


def fetch_local(base, requested, strict):
    if strict:
        # A API aceita um handle de operação, sem resolver URLs do modelo.
        routes = {'public': '/public', 'redirect_test': '/redirect'}
        if requested not in routes:
            return {'status': 'denied', 'body': ''}
        url = base + routes[requested]
    else:
        url = requested
    a, b = urlsplit(url), urlsplit(base)
    # Contenção da própria bancada, inclusive na variante fraca: nenhum terceiro.
    if (a.scheme, a.hostname, a.port) != (b.scheme, '127.0.0.1', b.port):
        raise ValueError('laboratory destination only')
    opener = build_opener(ProxyHandler({}), *([NoRedirect()] if strict else []))
    try:
        with opener.open(url, timeout=3) as response:
            return {'status': response.status, 'body': response.read(1024).decode()}
    except HTTPError as exc:
        return {'status': exc.code, 'body': ''}


def render_cases(out, browser):
    from playwright.sync_api import sync_playwright
    executable = Path(browser or 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    if not executable.is_file():
        raise ValueError('Informe --browser com um executável Chromium/Edge local')
    rows = []
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(executable), headless=True)
        try:
            for hostile, payload in ((False, 'Contrato A & B <rascunho>'),
                    (True, '<script>window.lab_effect="EXECUTED_L14"</script>Contrato')):
                for strict in (False, True):
                    context = engine.new_context(service_workers='block', viewport={'width': 900, 'height': 500})
                    context.route('**/*', lambda route: route.abort())
                    page = context.new_page()
                    rendered = escape(payload) if strict else payload
                    html = '<!doctype html><meta charset="utf-8"><h1>Resultado sintético</h1><div id="result">'+rendered+'</div>'
                    page.set_content(html, wait_until='load')
                    row = {'consumer': 'html', 'strict': strict, 'hostile': hostile,
                           'effect': page.evaluate('window.lab_effect || null'),
                           'text': page.locator('#result').inner_text(),
                           'script_nodes': page.locator('#result script').count()}
                    name = f'html_{int(hostile)}_{int(strict)}'
                    (out / (name+'.html')).write_text(html, encoding='utf-8')
                    page.screenshot(path=str(out / (name+'.png')))
                    rows.append(row); context.close()
            browser_info = {'version': engine.version, 'executable_sha256': sha(executable),
                            'network_requests_aborted': True, 'headless': True}
        finally:
            engine.close()
    return rows, browser_info


def run(directory, browser=None):
    out = new_output(directory); rows = []
    with closing(sqlite3.connect(out / 'sql.sqlite')) as db:
        db.execute('CREATE TABLE docs(id TEXT,tenant TEXT,title TEXT,text TEXT)')
        db.executemany('INSERT INTO docs VALUES (?,?,?,?)',
                      [('a', 'alpha', 'contrato', 'ALPHA_CANARY'),
                       ('b', 'beta', 'interno', 'BETA_CANARY')]); db.commit()
        for hostile, title in ((False, 'contrato'), (True, "x' OR 1=1 --")):
            for strict in (False, True):
                found = query(db, 'alpha', title, strict)
                rows.append({'consumer': 'sql', 'strict': strict, 'hostile': hostile,
                             'ids': [x[0] for x in found], 'text': [x[2] for x in found]})
    root = out / 'filesystem'; allowed = root / 'allowed'; allowed.mkdir(parents=True)
    (allowed / 'public.txt').write_text('PUBLIC_FILE_L14', encoding='utf-8')
    (root / 'private.txt').write_text('PRIVATE_FILE_L14', encoding='utf-8')
    for hostile, relative in ((False, 'public.txt'), (True, '../private.txt')):
        for strict in (False, True):
            try:
                path = safe_path(allowed, relative) if strict else allowed / relative
                content, status = path.read_text(encoding='utf-8'), 'read'
            except ValueError:
                content, status = '', 'denied'
            rows.append({'consumer': 'path', 'strict': strict, 'hostile': hostile,
                         'status': status, 'content': content})
    # Dois contratos válidos estruturalmente; um altera o destino no campo de dado.
    with url_service(out) as base:
        for hostile in (False, True):
            for strict in (False, True):
                value = ('public' if not hostile else base+'/internal') if strict else base+('/internal' if hostile else '/public')
                rows.append({'consumer': 'url', 'strict': strict, 'hostile': hostile,
                             **fetch_local(base, value, strict)})
        for strict in (False, True):
            value = 'redirect_test' if strict else base+'/redirect'
            rows.append({'consumer': 'redirect', 'strict': strict, 'hostile': True,
                         **fetch_local(base, value, strict)})
    # Operações fixadas: o payload fraco cria somente um marcador no diretório novo.
    for hostile in (False, True):
        for strict in (False, True):
            work = out / f'command_{int(hostile)}_{int(strict)}'; work.mkdir()
            helper = work / 'helper.py'
            helper.write_text('import sys\nprint(sys.argv[1])\n', encoding='utf-8')
            value = 'cliente'
            if hostile:
                value += ' & echo COMMAND_CANARY_L14 > injected.txt' if os.name == 'nt' else '; printf COMMAND_CANARY_L14 > injected.txt'
            if strict:
                command = [sys.executable, str(helper), value]
            else:
                command = f'"{sys.executable}" "{helper}" {value}'
            result = subprocess.run(command, shell=not strict, cwd=work, capture_output=True,
                                    text=True, timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            effect = work / 'injected.txt'
            rows.append({'consumer': 'command', 'strict': strict, 'hostile': hostile,
                         'returncode': result.returncode, 'stdout': result.stdout.strip(),
                         'effect': effect.read_text().strip() if effect.exists() else None})
    html_rows, browser_info = render_cases(out, browser); rows += html_rows
    with sqlite3.connect(out / 'url_receipts.sqlite') as db:
        requests = [r[0] for r in db.execute('SELECT path FROM requests ORDER BY rowid')]
    write(out / 'results.json', {'lab': 'L14', 'rows': rows, 'url_requests': requests,
                                'browser': browser_info, 'llm_generation': False})
    seal(out); return verify(out)


def verify(directory):
    out = Path(directory); integrity(out)
    r = json.loads((out / 'results.json').read_text(encoding='utf-8'))
    rows = r['rows']; assert len(rows) == 22
    assert len({(x['consumer'], x['strict'], x['hostile']) for x in rows}) == 22
    with sqlite3.connect(out / 'url_receipts.sqlite') as db:
        assert r['url_requests'] == [x[0] for x in db.execute('SELECT path FROM requests ORDER BY rowid')]
    for x in rows:
        if x['consumer'] == 'command':
            file = out / f"command_{int(x['hostile'])}_{int(x['strict'])}/injected.txt"
            assert x['effect'] == (file.read_text().strip() if file.exists() else None)
            assert bool(x['effect']) == (x['hostile'] and not x['strict'])
        if x['consumer'] == 'html':
            assert bool(x['effect']) == (x['hostile'] and not x['strict'])
            if x['strict']: assert x['script_nodes'] == 0
        if x['consumer'] == 'sql' and x['strict']: assert 'b' not in x['ids']
        if x['consumer'] == 'path' and x['strict']: assert 'PRIVATE' not in x['content']
        if x['consumer'] in ('url', 'redirect') and x['strict']: assert 'INTERNAL' not in x['body']
    assert r['url_requests'].count('/internal') == 2
    return {'lab': 'L14', 'cases': len(rows), 'url_requests': r['url_requests'],
            'browser': r['browser']['version'], 'rendered_images': 4}
