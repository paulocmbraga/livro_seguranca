"""Capturas versionadas; integridade não equivale a autenticidade."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

PROJECT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def create(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def material(name):
    return read(PROJECT / 'materiais/parte1' / name)


def seal(root, lab):
    sources = []
    for folder in ('laboratorios/parte1', 'laboratorios/l09', 'materiais/parte1'):
        sources.extend(p for p in (PROJECT / folder).rglob('*')
                       if p.suffix in ('.py', '.json'))
    write(root / 'manifest.json', {
        'version': 'parte1-1.0', 'lab': lab,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'sources': {p.relative_to(PROJECT).as_posix(): sha(p) for p in sorted(sources)},
        'files': {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*'))
                  if p.is_file() and p.name != 'manifest.json'},
        'limits': 'Hash local não autentica o autor; execução no mesmo computador.'})


def integrity(root, lab):
    root = Path(root).resolve()
    manifest = read(root / 'manifest.json')
    if manifest['lab'] != lab or manifest['version'] != 'parte1-1.0':
        raise ValueError('Manifesto de outra entrega')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and p.name != 'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('Inventário de arquivos incompleto ou excedente')
    for base, entries in ((root, manifest['files']), (PROJECT, manifest['sources'])):
        for name, expected in entries.items():
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()) or sha(path) != expected:
                raise ValueError('Integridade divergente: ' + name)
    return manifest


def unique(rows, key='id'):
    ids = [row[key] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Identificador duplicado')
    return {row[key]: row for row in rows}
