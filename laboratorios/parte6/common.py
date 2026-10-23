"""Infraestrutura local e formatos numéricos inspecionáveis, sem pickle."""
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from scipy.special import expit

PROJECT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def new_output(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def sources():
    return {p.relative_to(PROJECT).as_posix(): sha(p)
            for folder in ('laboratorios/parte6', 'materiais/parte6')
            for p in sorted((PROJECT / folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def seal(out):
    write(out / 'manifest.json', {
        'version': 'ParteVI-1.0', 'utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'libraries': {n: version(n) for n in ('numpy', 'scipy', 'scikit-learn')},
        'source_sha256': sources(),
        'artifacts_sha256': {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*'))
                            if p.is_file() and p.name != 'manifest.json'},
    })


def integrity(out):
    out = Path(out).resolve()
    m = read(out / 'manifest.json')
    actual = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    assert actual == set(m['artifacts_sha256']), 'inventário incompleto ou excedente'
    assert m['source_sha256'] == sources(), 'fontes diferentes da captura'
    for name, expected in m['artifacts_sha256'].items():
        p = (out / name).resolve()
        assert p.is_relative_to(out) and sha(p) == expected, name
    return m


@contextmanager
def database(path, **kwargs):
    connection = sqlite3.connect(path, **kwargs)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@contextmanager
def serve(dispatch):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 200000:
                status, result = 413, {'error': 'body_size'}
            else:
                try:
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('object required')
                    status, result = dispatch(self.path, self.headers, body)
                except (ValueError, KeyError, TypeError):
                    status, result = 400, {'error': 'invalid_request'}
            payload = json.dumps(result, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def call(url, token, body):
    request = Request(url, data=json.dumps(body).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        response = urlopen(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def matrix(rows):
    return np.asarray([r['x'] for r in rows], dtype=float), np.asarray([r['y'] for r in rows], dtype=int)


def linear_export(model):
    assert list(model.classes_) == [0, 1]
    return {'kind': 'logistic', 'coef': model.coef_[0].tolist(), 'intercept': float(model.intercept_[0]), 'classes': [0, 1]}


def linear_scores(model, x):
    x = np.asarray(x, dtype=float)
    return expit(x @ np.asarray(model['coef']) + model['intercept'])


def tree_export(model):
    t = model.tree_
    return {'kind': 'tree', 'classifier': hasattr(model, 'classes_'),
            'left': t.children_left.tolist(), 'right': t.children_right.tolist(),
            'feature': t.feature.tolist(), 'threshold': t.threshold.tolist(),
            'value': t.value[:, 0, :].tolist(),
            'classes': model.classes_.tolist() if hasattr(model, 'classes_') else None}


def tree_scores(model, x):
    # sklearn converte entradas de árvores para float32 na predição.
    x = np.asarray(x, dtype=np.float32)
    result = []
    for row in x:
        node = 0
        while model['left'][node] != -1:
            node = model['left'][node] if row[model['feature'][node]] <= model['threshold'][node] else model['right'][node]
        value = model['value'][node]
        if model['classifier']:
            score = value[model['classes'].index(1)] / sum(value) if 1 in model['classes'] else 0.0
        else:
            score = value[0]
        result.append(score)
    return np.asarray(result)


def accuracy(y, scores):
    y = np.asarray(y)
    predicted = np.asarray(scores) >= .5
    return {'n': int(len(y)), 'correct': int(np.sum(y == predicted)),
            'accuracy': float(np.mean(y == predicted))}


def assert_close(a, b):
    assert np.allclose(a, b, rtol=1e-8, atol=1e-10), 'valores numéricos divergentes'
