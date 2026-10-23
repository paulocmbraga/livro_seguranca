from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import platform
import sys

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
            for folder in ('laboratorios/parte7', 'materiais/parte7')
            for p in sorted((PROJECT / folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def seal(out):
    write(out / 'manifest.json', {
        'version': 'ParteVII-1.0', 'utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'libraries': {n: version(n) for n in ('numpy','scipy','scikit-learn','diffprivlib','torch','cryptography')},
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
