from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import hashlib
import json
import platform
import sqlite3
import sys

from laboratorios.parte6.common import database, serve, call

PROJECT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_bytes(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False).encode('utf-8'))


def new_output(path):
    out = Path(path).resolve(); out.mkdir(parents=True, exist_ok=False)
    return out


def sources():
    # Inclui módulos reutilizados; não altera seus selos históricos.
    folders = ('laboratorios', 'materiais/parte9')
    return {p.relative_to(PROJECT).as_posix(): sha(p) for folder in folders
            for p in sorted((PROJECT/folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def seal(out):
    write(out/'manifest.json', {'version':'ParteIX-1.0',
          'utc':datetime.now(timezone.utc).isoformat(), 'python':sys.version,
          'platform':platform.platform(), 'sqlite':sqlite3.sqlite_version,
          'libraries':{n:version(n) for n in ('numpy','scikit-learn','diffprivlib',
                         'mcp','a2a-sdk','cryptography','psutil')},
          'source_sha256':sources(), 'artifacts_sha256':{
              p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
              if p.is_file() and p.name != 'manifest.json'}})


def integrity(path):
    out=Path(path).resolve(); m=read(out/'manifest.json')
    actual={p.relative_to(out).as_posix() for p in out.rglob('*')
            if p.is_file() and p.name!='manifest.json'}
    assert actual==set(m['artifacts_sha256']), 'inventário'
    assert sources()==m['source_sha256'], 'fontes'
    for name, expected in m['artifacts_sha256'].items():
        p=(out/name).resolve()
        assert p.is_relative_to(out) and sha(p)==expected,name
    return m
