"""Inventário fechado de captura. Hash não substitui autoridade independente."""
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import platform
import sys

PROJECT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   allow_nan=False) + '\n', encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def create(path):
    out = Path(path).resolve()
    out.mkdir(parents=True, exist_ok=False)
    return out


def seal(out, lab):
    sources = sorted(p for folder in ('laboratorios/parte2', 'materiais/parte2')
                     for p in (PROJECT / folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    write(out / 'manifest.json', dict(
        version='parte2-1.0', lab=lab,
        created_utc=datetime.now(timezone.utc).isoformat(),
        runtime={'python': sys.version, 'platform': platform.platform(),
                 'PyJWT': version('PyJWT'), 'cryptography': version('cryptography')},
        sources={p.relative_to(PROJECT).as_posix(): sha(p.read_bytes()) for p in sources},
        files={p.relative_to(out).as_posix(): sha(p.read_bytes())
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}))


def integrity(out, lab):
    out = Path(out).resolve()
    manifest = read(out / 'manifest.json')
    if manifest['version'] != 'parte2-1.0' or manifest['lab'] != lab:
        raise ValueError('Captura de outro laboratório')
    actual = {p.relative_to(out).as_posix() for p in out.rglob('*')
              if p.is_file() and p.name != 'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('Inventário de captura divergente')
    for root, entries in ((out, manifest['files']), (PROJECT, manifest['sources'])):
        for name, expected in entries.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or sha(path.read_bytes()) != expected:
                raise ValueError('Hash divergente: ' + name)
    return manifest
