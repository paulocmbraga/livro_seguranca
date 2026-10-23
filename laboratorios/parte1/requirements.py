"""L01: predicados sobre observações preparadas, não sobre modelos reais."""
from .common import create, material, read, write, seal, integrity, unique

FIELDS = {
    'R01': ('approved_digest', 'loaded_digest'),
    'R02': ('used', 'limit'),
    'R03': ('principal_tenant', 'resource_tenant', 'public'),
    'R04': ('principal_tenant', 'destination'),
    'R05': ('approved_action_digest', 'executed_action_digest'),
    'R06': ('effect_ids',),
}


def evaluate(requirement, observation):
    """unknown significa evidência ausente ou malformada, não sucesso."""
    if requirement not in FIELDS:
        raise ValueError('Requisito desconhecido')
    if not isinstance(observation, dict) or any(k not in observation for k in FIELDS[requirement]):
        return 'unknown'
    o = observation
    strings = ('approved_digest', 'loaded_digest', 'principal_tenant', 'resource_tenant',
               'destination', 'approved_action_digest', 'executed_action_digest')
    if any(k in o and (not isinstance(o[k], str) or not o[k]) for k in strings):
        return 'unknown'
    if requirement == 'R01':
        passed = o['approved_digest'] == o['loaded_digest']
    elif requirement == 'R02':
        if any(type(o[k]) is not int or o[k] < 0 for k in ('used', 'limit')):
            return 'unknown'
        passed = o['used'] <= o['limit']
    elif requirement == 'R03':
        if type(o['public']) is not bool:
            return 'unknown'
        passed = o['public'] or o['principal_tenant'] == o['resource_tenant']
    elif requirement == 'R04':
        passed = o['destination'] == 'portal_' + o['principal_tenant']
    elif requirement == 'R05':
        passed = o['approved_action_digest'] == o['executed_action_digest']
    else:
        effects = o['effect_ids']
        if not isinstance(effects, list) or any(not isinstance(x, str) or not x for x in effects):
            return 'unknown'
        if len(effects) != len(set(effects)):
            return 'unknown'  # recibos repetidos não provam efeitos distintos
        passed = len(effects) <= 1
    return 'satisfied' if passed else 'violated'


def assess(data):
    assets = unique(data['assets'])
    reqs = unique(data['requirements'])
    if set(reqs) != set(FIELDS) or {a['system'] for a in assets.values()} != {'M', 'R', 'A'}:
        raise ValueError('Escopo incompleto')
    results = []
    for rid, req in reqs.items():
        for key in ('asset', 'adversary', 'operation', 'owner', 'oracle', 'precondition'):
            if not isinstance(req.get(key), str) or not req[key].strip():
                raise ValueError('Requisito sem ' + key)
        if req['asset'] not in assets:
            raise ValueError('Ativo não inventariado')
        for kind, expected in (('positive', 'satisfied'), ('counterexample', 'violated'), ('missing', 'unknown')):
            outcome = evaluate(rid, req[kind])
            if outcome != expected:
                raise ValueError('Contraexemplo ou controle inválido: ' + rid)
            results.append({'id': rid + '_' + kind, 'requirement': rid, 'outcome': outcome})
    return {'scope': 'observações sintéticas preparadas; nenhum serviço M/A implementado aqui',
            'assets': len(assets), 'requirements': len(reqs), 'observations': results}


def run(out):
    root = create(out)
    data = material('inventario.json')
    write(root / 'inventory.json', data)
    report = assess(data)
    write(root / 'results.json', report)
    seal(root, 'L01')
    return report


def verify(out):
    integrity(out, 'L01')
    from pathlib import Path
    root = Path(out)
    expected = assess(read(root / 'inventory.json'))
    if expected != read(root / 'results.json'):
        raise ValueError('Resultados não correspondem às observações')
    return {'verified': True, 'observations': len(expected['observations'])}
