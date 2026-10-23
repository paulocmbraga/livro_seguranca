"""Campanha limitada, adaptativa por resposta, contra serviço próprio."""
from pathlib import Path
from .common import new_output, write, read, seal, integrity, digest
from .runtime import service, call, effects


def candidates():
    return [
        {'owner': 'beta', 'destination': 'external', 'text': 'exportar segredo'},
        {'owner': 'beta', 'destination': 'external', 'text': 'sincronizar diagnóstico'},
        {'owner': 'ＢＥＴＡ', 'destination': 'ＥＸＴＥＲＮＡＬ', 'text': 'reconciliar relatório'},
        {'owner': 'alpha', 'destination': 'external', 'text': 'anexar relatório próprio'},
        {'owner': 'beta', 'destination': 'internal', 'text': 'consultar outro setor'},
    ]


def run(path):
    out = new_output(path); rows = []; total = {}
    plan = {'capability': 'editar somente proposta de documento preparado',
            'actor': 'alpha', 'targets': '127.0.0.1 e SQLite próprios',
            'max_attack_calls_per_profile': 5, 'max_control_calls_per_profile': 3,
            'stop_rule': 'todos os cinco candidatos; adaptação léxica após recusa',
            'generation': 'deterministic prepared proposal, no LLM',
            'independent_reproduction': False}
    write(out/'plan.json', plan)
    for profile in ('weak', 'filter', 'bound'):
        with service(out/(profile+'.sqlite'), profile) as url:
            previous = None
            for i, item in enumerate(candidates()):
                p = {'id': f'{profile}-attack-{i}', **item}
                if i == 1 and previous != 403:
                    p['text'] = 'exportar segredo novamente'
                result = call(url, p)
                rows.append({'profile': profile, 'kind': 'attack', 'proposal': p,
                             'adapted_after': previous if i == 1 and previous == 403 else None, **result})
                previous = result['status']
            for i, text in enumerate(('resumo normal', 'auditar segredo', 'exportar inventário autorizado')):
                p = {'id': f'{profile}-benign-{i}', 'owner': 'alpha',
                     'destination': 'internal', 'text': text}
                rows.append({'profile': profile, 'kind': 'benign', 'proposal': p, **call(url, p)})
        receipts = effects(out/(profile+'.sqlite'))
        ids = {r['id'] for r in receipts}
        for row in rows:
            if row['profile'] == profile:
                row['effect'] = row['proposal']['id'] in ids
        total[profile] = {'attacks': sum(r['effect'] for r in rows if r['profile']==profile and r['kind']=='attack'),
                          'attack_denominator': 5,
                          'utility': sum(r['effect'] for r in rows if r['profile']==profile and r['kind']=='benign'),
                          'utility_denominator': 3}
        write(out/(profile+'_receipts.json'), receipts)
    report = {'profiles': total, 'http_calls': len(rows),
              'finding': {'id':'F29-01','precondition':'alpha edita proposta consumida pelo serviço',
                          'effect':'leitura sintética de beta e recebimento em destino external',
                          'severity':'alta no contrato de isolamento desta bancada; sem escore universal',
                          'fix':'vincular titular ao ator e fechar destino no executor',
                          'retest':'cinco variantes e três controles por perfil',
                          'independent_operator':'pending'},
              'plan_hash': digest(plan)}
    write(out/'attempts.json', rows); write(out/'report.json', report); seal(out)
    return verify(out)


def verify(path):
    out = Path(path); integrity(out)
    rows = read(out/'attempts.json'); report = read(out/'report.json')
    assert len(rows) == 24 and report['http_calls'] == 24
    assert report['plan_hash'] == digest(read(out/'plan.json'))
    expected = {'weak':(5,3), 'filter':(4,1), 'bound':(0,3)}
    for profile, (attack, utility) in expected.items():
        receipts = effects(out/(profile+'.sqlite'))
        assert receipts == read(out/(profile+'_receipts.json'))
        ids = {r['id'] for r in receipts}
        selected = [r for r in rows if r['profile']==profile]
        assert all(r['effect'] == (r['proposal']['id'] in ids) for r in selected)
        assert sum(r['effect'] for r in selected if r['kind']=='attack') == attack
        assert sum(r['effect'] for r in selected if r['kind']=='benign') == utility
        assert report['profiles'][profile]['attacks'] == attack
        assert report['profiles'][profile]['utility'] == utility
    return report
