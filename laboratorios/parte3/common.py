import hashlib
import json
from pathlib import Path
import platform
import sys
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[2]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def new_output(directory):
    out = Path(directory).resolve()
    out.mkdir(parents=True, exist_ok=False)
    return out


def seal(out):
    out = Path(out)
    sources = [p for folder in ('laboratorios/parte3', 'materiais/parte3')
               for p in (PROJECT / folder).rglob('*')
               if p.is_file() and '__pycache__' not in p.parts]
    write(out / 'manifest.json', {
        'version': 'ParteIII-1.0', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'source_sha256': {p.relative_to(PROJECT).as_posix(): sha(p) for p in sorted(sources)},
        'artifacts_sha256': {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*'))
                            if p.is_file() and p != out / 'manifest.json'},
    })


def integrity(out):
    out = Path(out).resolve()
    m = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(out).as_posix() for p in out.rglob('*')
              if p.is_file() and p != out / 'manifest.json'}
    if actual != set(m['artifacts_sha256']):
        raise ValueError('Inventário de captura incompleto ou excedente')
    for root, key in ((out, 'artifacts_sha256'), (PROJECT, 'source_sha256')):
        for name, digest in m[key].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or sha(path) != digest:
                raise ValueError('Integridade divergente: ' + name)
    return m
