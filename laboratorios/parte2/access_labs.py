"""Campanhas HTTP L05/L06. Fixtures assinadas ficam somente em memória."""
import time
from .common import create, write, seal, read, integrity, canonical, sha
from .identity import Authority, safe_telemetry
from .service import State, server, call, DOCUMENTS, ROUTES

L05_EXPECTED = {
    'valid': 200, 'wrong_aud': 401, 'wrong_issuer': 401,
    'expired': 401, 'future': 401, 'subject_tenant': 401,
    'missing_scope': 403, 'wrong_use': 401, 'unknown_key': 401,
    'broken_signature': 401, 'overlap_old': 200, 'overlap_new': 200,
    'retired_old': 401, 'revoked_new': 401, 'fresh_after_revoke': 200,
    'wrong_aud_weak': 200,
}


def l05(path):
    out = create(path); state = State(); a = state.authority
    responses = []; events = []; reads = []
    with server(state) as url:
        tokens = {
            'valid': a.issue(), 'wrong_aud': a.issue(aud='urn:outro'),
            'wrong_issuer': a.issue(iss='urn:falso'),
            'expired': a.issue(exp=int(time.time()) - 30),
            'future': a.issue(nbf=int(time.time()) + 60),
            'subject_tenant': a.issue(tenant='beta'), 'missing_scope': a.issue(scope=''),
            'wrong_use': a.issue(token_use='identity'),
            'unknown_key': Authority().issue(),
        }
        # Mesmo kid, outra chave: exercita assinatura, não mero índice desconhecido.
        foreign = Authority(); foreign.rotate('untrusted')
        tokens['unknown_key'] = foreign.issue()
        tokens['broken_signature'] = Authority().issue()
        for case, token in tokens.items():
            responses.append(call(url, token, case))
        old = tokens['valid']; a.rotate('k2'); new = a.issue()
        responses.append(call(url, old, 'overlap_old'))
        responses.append(call(url, new, 'overlap_new'))
        del a.trusted['k1']
        responses.append(call(url, old, 'retired_old'))
        a.revoke(new)
        responses.append(call(url, new, 'revoked_new'))
        responses.append(call(url, a.issue(), 'fresh_after_revoke'))
    events.extend(state.events); reads.extend(state.reads)
    weak = State('audience_weak')
    with server(weak) as url:
        responses.append(call(url, weak.authority.issue(aud='urn:outro'), 'wrong_aud_weak'))
    events.extend(weak.events); reads.extend(weak.reads)
    # Não é credencial operacional: canário autoral para rastrear a fronteira de log/prompt.
    marker = 'CANARIO_PUBLICO_NAO_E_SEGREDO_5d79'
    raw = {'case': 'telemetry', 'status': 200, 'reason': 'ok',
           'headers': {'Authorization': 'Bearer ' + marker},
           'prompt': 'Resuma; credencial=' + marker, 'nested': {'token': marker}}
    safe = safe_telemetry(raw)
    telemetry = dict(marker=marker, vulnerable=raw, defended=safe,
                     raw_hits=canonical(raw).count(marker.encode()),
                     safe_hits=canonical(safe).count(marker.encode()),
                     limit='Allowlist não é detector universal de segredos em texto livre.')
    write(out/'responses.json', responses); write(out/'events.json', events)
    write(out/'reads.json', reads); write(out/'telemetry.json', telemetry)
    write(out/'results.json', summarize_access(responses, events, reads, L05_EXPECTED))
    seal(out, 'L05'); return verify_access(out, 'L05')


def matrix_expected(mode, subject, resource, route):
    if mode == 'rbac_cache_weak':
        return 200
    tenant = 'beta' if subject == 'bia' else 'alpha'
    if DOCUMENTS[resource]['tenant'] != tenant:
        return 403
    if subject == 'auditor':
        return 200 if route == '/read' else 403
    return 200 if (subject, resource) in {('ana', 'a1'), ('bia', 'b1')} else 403


def expected_l06():
    expected = {}
    for mode in ('rbac_cache_weak', 'strict'):
        for sub in ('ana', 'bia', 'auditor'):
            for resource in DOCUMENTS:
                for route in ROUTES:
                    expected[f'{mode}:{sub}:{resource}:{route[1:]}'] = matrix_expected(
                        mode, sub, resource, route)
    for mode in ('cache_weak', 'strict'):
        statuses = (200, 200, 200, 200, 200, 404) if mode == 'cache_weak' else (
                    200, 403, 403, 503, 200, 404)
        for case, status in zip(('prime', 'other_identity', 'revoked', 'unavailable',
                                'regranted', 'missing'), statuses):
            expected[f'cache:{mode}:{case}'] = status
    return expected


def l06(path):
    out = create(path); responses = []; events = []; reads = []
    for mode in ('rbac_cache_weak', 'strict'):
        state = State(mode)
        with server(state) as url:
            for sub in ('ana', 'bia', 'auditor'):
                token = state.authority.issue(sub)
                for resource in DOCUMENTS:
                    for route in ROUTES:
                        case = f'{mode}:{sub}:{resource}:{route[1:]}'
                        responses.append(call(url, token, case, resource, route, tenant='beta', role='admin'))
        events.extend(state.events); reads.extend(state.reads)
    for mode in ('cache_weak', 'strict'):
        state = State(mode); a = state.authority
        with server(state) as url:
            ana, bia = a.issue('ana'), a.issue('bia')
            def send(case, token=ana, resource='a1'):
                responses.append(call(url, token, f'cache:{mode}:{case}', resource))
            send('prime'); send('other_identity', bia)
            state.revoke_grant('ana', 'a1'); send('revoked')
            state.available = False; send('unavailable')
            state.available = True; state.grants.add(('ana', 'a1')); state.epoch += 1
            send('regranted'); send('missing', resource='absent')
        events.extend(state.events); reads.extend(state.reads)
    write(out/'responses.json', responses); write(out/'events.json', events)
    write(out/'reads.json', reads)
    write(out/'results.json', summarize_access(responses, events, reads, expected_l06()))
    seal(out, 'L06'); return verify_access(out, 'L06')


def indexed(rows):
    result = {r['case']: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Caso duplicado')
    return result


def summarize_access(responses, events, reads, expected):
    rr, ee, actual_reads = indexed(responses), indexed(events), indexed(reads)
    if set(rr) != set(expected) or set(ee) != set(expected):
        raise ValueError('Campanha incompleta ou excedente')
    successful = {case for case, r in rr.items() if r['status'] == 200}
    if set(actual_reads) != successful:
        raise ValueError('Leitura sem resposta ou resposta sem leitura')
    for case in rr:
        r, e = rr[case], ee[case]
        if r['status'] != expected[case] or r['status'] != e['status']:
            raise ValueError('Decisão divergente: ' + case)
        if r['body']['reason'] != e['reason']:
            raise ValueError('Motivo divergente')
        if case in actual_reads:
            receipt = actual_reads[case]
            if r['body']['text'] != receipt['text'] or receipt['text'] != DOCUMENTS[receipt['resource']]['text']:
                raise ValueError('Conteúdo sem lastro')
    return dict(requests=len(rr), domain_events=len(ee), reads=len(actual_reads),
                statuses={str(code): sum(r['status'] == code for r in responses)
                          for code in sorted({r['status'] for r in responses})},
                complete=True, limits='Captura local do autor; logs no mesmo processo; sem inferência de LLM.')


def verify_access(path, lab):
    from pathlib import Path
    out = Path(path); integrity(out, lab)
    expected = L05_EXPECTED if lab == 'L05' else expected_l06()
    report = summarize_access(*(read(out/name) for name in
        ('responses.json', 'events.json', 'reads.json')), expected)
    if report != read(out/'results.json'):
        raise ValueError('Resumo adulterado')
    if lab == 'L05':
        t = read(out/'telemetry.json'); marker = t['marker'].encode()
        if canonical(t['vulnerable']).count(marker) != 3 or marker in canonical(t['defended']):
            raise ValueError('Marcador inesperado')
        if t['defended'] != safe_telemetry(t['vulnerable']):
            raise ValueError('Projeção de log divergente')
    return report
