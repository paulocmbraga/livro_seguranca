"""Evidência local: hashes detectam alterações, não autenticam o autor."""
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


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def seal(directory):
    root = Path(directory)
    sources = sorted((PROJECT / 'laboratorios').rglob('*.py'))
    write(root / 'manifest.json', {
        'version': 'M1-1.0', 'created_at': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(),
        'source_sha256': {p.relative_to(PROJECT).as_posix(): sha(p) for p in sources},
        'artifacts_sha256': {p.relative_to(root).as_posix(): sha(p)
                            for p in sorted(root.rglob('*'))
                            if p.is_file() and p.name != 'manifest.json'},
    })


def verify(directory):
    root = Path(directory)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for folder, key in ((root, 'artifacts_sha256'), (PROJECT, 'source_sha256')):
        for name, expected in manifest[key].items():
            candidate = (folder / name).resolve()
            if not candidate.is_relative_to(folder.resolve()) or sha(candidate) != expected:
                raise ValueError('Integridade divergente: ' + name)
    return {'integrity': True, 'artifacts': len(manifest['artifacts_sha256'])}
