"""Run cria captura; verify confere arquivos e recompõe operações locais pequenas."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import tempfile

from .core import counts, digest, impact, reconcile, reference_key, strict_json, verify_files, wilson

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, v):
    Path(p).write_bytes(json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))


def sources():
    return {p.relative_to(ROOT).as_posix(): sha(p)
            for folder in ('apoio_apendices', 'materiais/apendices')
            for p in sorted((ROOT / folder).rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def fixture():
    return strict_json((ROOT / 'materiais/apendices/casos.json').read_text(encoding='utf-8'))


def compute():
    f = fixture()
    report = {'metrics': counts(f['cases']), 'wilson_zero_twenty': wilson(0, 20),
              'reconciliation': reconcile(f['plans'], f['receipts'], f['audits']),
              'migration': impact(f['before'], f['after'], f['dependencies']),
              'reference_keys': [list(reference_key(r)) for r in f['references']]}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'evidence.txt'
        path.write_bytes(b'synthetic receipt\n')
        manifest = [{'path': path.name, 'sha256': sha(path), 'bytes': path.stat().st_size}]
        report['manifest_valid'] = verify_files(directory, manifest)
        path.write_bytes(b'altered receipt!!\n')
        try:
            verify_files(directory, manifest)
        except ValueError as error:
            report['tamper_refused'] = str(error)
        else:
            raise RuntimeError('tamper_not_detected')
    return report


def run(path):
    out = Path(path).resolve()
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'results.json', compute())
    write(out / 'environment.json', {'python': platform.python_version(),
          'system': platform.system(), 'sqlite': sqlite3.sqlite_version,
          'network_calls': 0, 'llm_generations': 0, 'new_docker_runs': 0,
          'evidence': 'Local prepared records; historical lab captures are not reexecuted.'})
    write(out / 'manifest.json', {'version': 'Apendices-1.0',
          'utc': datetime.now(timezone.utc).isoformat(), 'sources': sources(),
          'files': [{'path': p.name, 'sha256': sha(p), 'bytes': p.stat().st_size}
                    for p in sorted(out.iterdir()) if p.is_file()]})
    verify(out)


def verify(path):
    out = Path(path).resolve()
    manifest = strict_json((out / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['sources'] != sources():
        raise ValueError('sources')
    expected = {r['path'] for r in manifest['files']} | {'manifest.json'}
    actual = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
    if actual != expected:
        raise ValueError('inventory')
    verify_files(out, manifest['files'])
    result = strict_json((out / 'results.json').read_text(encoding='utf-8'))
    if digest(result) != digest(compute()):
        raise ValueError('reconciliation')
    print(json.dumps({'capture': str(out), 'checked': True, 'independent_review': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('run', 'verify'))
    parser.add_argument('--out', required=True)
    arguments = parser.parse_args()
    (run if arguments.action == 'run' else verify)(arguments.out)
