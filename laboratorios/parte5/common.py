import hashlib
import json
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def new_output(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def sources():
    paths = [p for folder in ('laboratorios/parte5', 'materiais/parte5')
             for p in (PROJECT / folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts]
    # Serviços, emissor e tipos reutilizados do ensaio M1, sem alterar sua fonte.
    paths.extend(p for p in (PROJECT / 'laboratorios/m1').glob('*.py'))
    return {p.relative_to(PROJECT).as_posix(): sha(p) for p in sorted(paths)}


def seal(out):
    write(out / 'manifest.json', {
        'version': 'ParteV-1.0', 'utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'source_sha256': sources(),
        'artifacts_sha256': {p.relative_to(out).as_posix(): sha(p)
                            for p in sorted(out.rglob('*'))
                            if p.is_file() and p.name != 'manifest.json'},
    })


def integrity(out):
    out = Path(out).resolve()
    m = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(out).as_posix() for p in out.rglob('*')
              if p.is_file() and p.name != 'manifest.json'}
    assert actual == set(m['artifacts_sha256']), 'inventário incompleto ou excedente'
    assert m['source_sha256'] == sources(), 'fontes diferentes da captura'
    for name, digest in m['artifacts_sha256'].items():
        p = (out / name).resolve()
        assert p.is_relative_to(out) and sha(p) == digest, name
    return m


from contextlib import contextmanager
import sqlite3

@contextmanager
def database(path, **options):
    connection = sqlite3.connect(path, **options)
    try:
        with connection:
            yield connection
    finally:
        connection.close()
