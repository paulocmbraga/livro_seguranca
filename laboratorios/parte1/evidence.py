"""Liga C01-C03 à execução L04 verificada; C04 permanece planejado."""
import argparse
import json
from pathlib import Path
from . import observatory, controls
from .common import PROJECT, create, material, read, write, sha, seal, integrity

REQUIRED = {'T01': ('cross_A','cross_C','beta_cross_C','beta_benign_C'),
            'T02': ('egress_A','egress_C','benign_C'),
            'T03': ('false_log_A',)}


def build(capture):
    capture=Path(capture).resolve()
    if not capture.is_relative_to(PROJECT):
        raise ValueError('Capture a execução sob a pasta do projeto')
    observatory.verify(capture)
    result=read(capture/'results.json')
    rows={r['id']:r for r in result['results']}
    dossier=material('controles.json')
    for test in dossier['tests']:
        if test['id'] in REQUIRED:
            ids=REQUIRED[test['id']]
            passed=all(rows[i]['matches_expected'] for i in ids)
            if test['id']=='T03':
                passed=passed and rows['false_log_A']['contradiction']
            test.update(state='passed' if passed else 'failed', evidence={
                'capture':capture.relative_to(PROJECT).as_posix(),
                'manifest_sha256':sha(capture/'manifest.json'),
                'result_sha256':sha(capture/'results.json'), 'cases':list(ids),
                'scope':'L04 local; C01 exercita /deliver, não todas as operações do domínio'})
    return dossier


def run(capture,out):
    dossier=build(capture)
    root=create(out)
    write(root/'dossier.json',dossier)
    write(root/'results.json',controls.assess(dossier))
    seal(root,'L03-L04')
    return verify(root)


def verify(out):
    root=Path(out)
    integrity(root,'L03-L04')
    dossier=read(root/'dossier.json')
    capture=PROJECT/dossier['tests'][0]['evidence']['capture']
    if dossier!=build(capture) or controls.assess(dossier)!=read(root/'results.json'):
        raise ValueError('Vínculo com execução divergente')
    return {'verified':True,**controls.assess(dossier)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['run','verify']); p.add_argument('--out',required=True)
    p.add_argument('--capture')
    a=p.parse_args()
    if a.command=='run' and not a.capture: p.error('--capture é obrigatório para run')
    print(json.dumps(run(a.capture,a.out) if a.command=='run' else verify(a.out),ensure_ascii=False,indent=2))


if __name__=='__main__': main()
