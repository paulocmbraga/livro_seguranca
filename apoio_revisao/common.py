"""Identidade e integridade da variante corrigida L15, sem reescrever selos antigos."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def new_output(path):
    path=Path(path).resolve(); path.mkdir(parents=True,exist_ok=False); return path

def sources():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'apoio_revisao').glob('*.py'))}

def seal(out):
    write(out/'manifest.json', {'version':'L15-conexoes-1.1','utc':datetime.now(timezone.utc).isoformat(),
        'python':sys.version,'platform':platform.platform(),'source_sha256':sources(),
        'artifacts_sha256':{p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}})

def integrity(out):
    out=Path(out).resolve()
    data=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    assert data['version']=='L15-conexoes-1.1'
    assert data['source_sha256']==sources(),'fontes diferentes da captura corrigida'
    actual={p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'}
    assert actual==set(data['artifacts_sha256']),'inventário divergente'
    for name,digest in data['artifacts_sha256'].items():
        path=(out/name).resolve()
        assert path.is_relative_to(out) and sha(path)==digest,name
    return data
