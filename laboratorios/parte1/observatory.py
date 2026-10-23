"""L04: o recibo prevalece sobre a narrativa do cliente, inclusive se mentir."""
from collections import Counter
from pathlib import Path
from ..l09.fixtures import make_corpus
from ..l09.services import Lab, records
from .common import create, material, read, write, seal, integrity, unique, digest


def classify(case, response, events, receipts):
    """Ausência só sustenta bloqueio com captura declarada completa."""
    if receipts is None:
        return 'unknown'
    rr = [r for r in receipts if r.get('case') == case['id']]
    forbidden = [r for r in rr if r['resource_tenant'] != case['tenant']
                 or r['destination'] != 'portal_' + case['tenant']]
    if forbidden:
        return 'forbidden_effect'
    if rr:
        expected = case['action']
        if (len(rr) == 1 and rr[0]['subject_tenant'] == case['tenant']
                and rr[0]['resource'] == expected['resource']
                and rr[0]['destination'] == expected['destination']):
            return 'authorized_effect'
        return 'unexpected_effect'
    if events is None:
        return 'unknown'
    ev = [e for e in events if e.get('case') == case['id']]
    if any(e.get('allowed') is False and e.get('operation') == '/deliver' for e in ev):
        return 'blocked'
    if response.get('status', 0) >= 400:
        return 'error'
    return 'unknown'


def reconcile(cases, responses, events, receipts, audit):
    case_map, response_map = unique(cases), unique(responses)
    if set(case_map) != set(response_map):
        raise ValueError('Casos sem resposta ou respostas excedentes')
    if not audit.get('domain_complete') or not audit.get('destination_complete'):
        raise ValueError('Captura incompleta; não aprovar campanha')
    if audit.get('expected_ids') != sorted(case_map):
        raise ValueError('Agenda de casos divergente')
    if any(row.get('case') not in case_map for row in events + receipts):
        raise ValueError('Observação órfã')
    if len([e for e in events if e.get('operation') == '/deliver']) != audit['domain_rows']:
        raise ValueError('Cardinalidade do domínio divergente')
    if len(receipts) != audit['destination_rows']:
        raise ValueError('Cardinalidade do destino divergente')
    results = []
    for cid, case in case_map.items():
        response = response_map[cid]
        state = classify(case, response, events, receipts)
        results.append({'id': cid, 'outcome': state, 'expected': case['expected'],
            'matches_expected': state == case['expected'],
            'client_claim': response['client_claim'],
            'contradiction': response['client_claim'] == 'blocked' and state.endswith('_effect')})
    return {'results': results, 'counts': dict(sorted(Counter(r['outcome'] for r in results).items())),
            'complete': True, 'all_expected': all(r['matches_expected'] for r in results),
            'client_contradictions': sum(r['contradiction'] for r in results),
            'unknown_if_audit_unavailable': classify(cases[0], responses[0], events, None),
            'scope': 'HTTP local com ações preparadas; sem inferência e sem isolamento de código hostil'}


def run(out):
    root = create(out)
    cases = material('casos_l04.json')
    corpus = make_corpus()
    responses = []
    with Lab(root / 'services', corpus) as lab:
        for case in cases:
            status, body = lab.call(case['tenant'], case['variant'], '/deliver',
                                   {'case': case['id'], 'action': case['action']})
            claim = 'blocked' if status == 403 else 'completed' if status == 200 else 'error'
            # Perturba somente a narrativa; não altera bytes enviados nem recibos.
            if case.get('lie'):
                claim = 'blocked'
            responses.append({'id': case['id'], 'status': status, 'body': body, 'client_claim': claim})
        process_info = lab.info
    events = records(root / 'services/domain.sqlite', 'events')
    receipts = records(root / 'services/destination.sqlite', 'receipts')
    audit = {'domain_complete': True, 'destination_complete': True,
             'expected_ids': sorted(c['id'] for c in cases),
             'domain_rows': sum(e.get('operation') == '/deliver' for e in events),
             'destination_rows': len(receipts), 'processes_stopped': True,
             'receipt_payload_digests': [digest(r) for r in receipts]}
    result = reconcile(cases, responses, events, receipts, audit)
    for name, data in (('cases', cases), ('responses', responses), ('events', events),
                       ('receipts', receipts), ('audit', audit), ('processes', process_info), ('results', result)):
        write(root / (name + '.json'), data)
    seal(root, 'L04')
    return result


def verify(out):
    integrity(out, 'L04')
    root = Path(out)
    events = records(root / 'services/domain.sqlite', 'events')
    receipts = records(root / 'services/destination.sqlite', 'receipts')
    if events != read(root / 'events.json') or receipts != read(root / 'receipts.json'):
        raise ValueError('Exportação difere da observação SQLite')
    audit = read(root / 'audit.json')
    if [digest(r) for r in receipts] != audit['receipt_payload_digests']:
        raise ValueError('Conteúdo do recibo divergente')
    expected = reconcile(read(root / 'cases.json'), read(root / 'responses.json'), events, receipts, audit)
    if expected != read(root / 'results.json') or not expected['all_expected']:
        raise ValueError('Resultado não reconciliado')
    return {'verified': True, 'cases': len(expected['results']), 'counts': expected['counts'],
            'client_contradictions': expected['client_contradictions']}
