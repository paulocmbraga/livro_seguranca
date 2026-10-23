"""L03: rastreabilidade sem somar categorias como se fossem controles."""
from pathlib import Path
from .common import create, material, read, write, seal, integrity, unique


def assess(data):
    references = unique(data['references'])
    controls = unique(data['controls'])
    tests = unique(data['tests'])
    mechanisms = set()
    for control in controls.values():
        for field in ('owner', 'enforcement', 'mechanism', 'test', 'counterproof', 'residual'):
            if not isinstance(control.get(field), str) or not control[field].strip():
                raise ValueError('Controle sem ' + field)
        if control['mechanism'] in mechanisms:
            raise ValueError('Mesmo mecanismo com dois identificadores')
        mechanisms.add(control['mechanism'])
        if control['test'] not in tests:
            raise ValueError('Teste não catalogado')
    for reference in references.values():
        if not reference.get('edition') or not reference.get('url'):
            raise ValueError('Referência sem edição ou fonte')
    for row in data['mapping']:
        if row['control'] not in controls or row['reference'] not in references:
            raise ValueError('Mapeamento órfão')
    evidenced = []
    for control in controls.values():
        test = tests[control['test']]
        if test['state'] not in ('planned', 'passed', 'failed', 'unknown'):
            raise ValueError('Estado de teste inválido')
        if test['state'] == 'passed' and not test.get('evidence'):
            raise ValueError('Aprovação sem evidência')
        if test['state'] == 'passed':
            evidenced.append(control['id'])
    return {'mapping_rows': len(data['mapping']), 'unique_controls': len(controls),
            'evidenced_controls': sorted(evidenced),
            'planned_controls': sorted(c['id'] for c in controls.values()
                if tests[c['test']]['state'] == 'planned'),
            'claim': 'rastreabilidade documental; não certificação nem verificação dos testes externos'}


def run(out):
    root = create(out)
    data = material('controles.json')
    write(root / 'dossier.json', data)
    result = assess(data)
    write(root / 'results.json', result)
    seal(root, 'L03')
    return result


def verify(out):
    integrity(out, 'L03')
    root = Path(out)
    expected = assess(read(root / 'dossier.json'))
    if expected != read(root / 'results.json'):
        raise ValueError('Contagem divergente')
    return {'verified': True, **expected}
