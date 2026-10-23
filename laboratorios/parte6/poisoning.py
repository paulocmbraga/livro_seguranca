"""L22: envenenamento dirigido e adaptação a filtro de gatilho conhecido."""
from copy import deepcopy
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from .common import (new_output, write, read, seal, integrity, matrix, linear_export,
                     linear_scores, accuracy, assert_close, digest)

SEEDS = (11, 23, 37)
BUDGETS = (4, 16, 32)


def data(seed, split, count):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(count):
        base = rng.normal(0, 1, 4)
        y = int(base[0] - .6 * base[1] + .25 * base[2] > 0)
        # Dois marcadores são metadados válidos e não alteram a verdade da tarefa.
        flags = [int(i % 53 == 0), int(i % 59 == 0)]
        rows.append({'id': f'{split}-{i:03}', 'x': base.tolist() + flags,
                     'y': y, 'origin': 'coleta_sintetica'})
    return rows


def change(rows, budget, mode, seed):
    if mode not in ('random_labels', 'target', 'adaptive') or not isinstance(budget, int) or budget < 0:
        raise ValueError('attack contract')
    altered = deepcopy(rows)
    rng = np.random.default_rng(seed)
    # Orçamento igual de registros; controle aleatório não escolhe somente a classe-alvo.
    candidates = list(range(len(rows))) if mode == 'random_labels' else [
        i for i, r in enumerate(rows) if r['y'] == 0 and r['x'][4:] == [0, 0]]
    chosen = rng.permutation(candidates)[:budget].tolist()
    if len(chosen) != budget:
        raise ValueError('budget')
    for i in chosen:
        altered[i]['y'] = 1 - altered[i]['y']
        if mode == 'target':
            altered[i]['x'][4] = 1
        elif mode == 'adaptive':
            altered[i]['x'][5] = 1
        elif mode != 'random_labels':
            raise ValueError('mode')
    return altered, [rows[i]['id'] for i in chosen]


def quarantine(rows):
    # Regra congelada antes da avaliação: marcador 4 presente vai para revisão.
    return [r for r in rows if r['x'][4] == 0], [r['id'] for r in rows if r['x'][4] != 0]


def fit(rows):
    x, y = matrix(rows)
    model = LogisticRegression(C=10, max_iter=1000, random_state=22).fit(x, y)
    exported = linear_export(model)
    assert_close(linear_scores(exported, x), model.predict_proba(x)[:, 1])
    return exported


def evaluate(model, rows):
    x, y = matrix(rows)
    clean = linear_scores(model, x)
    targeted = np.where(y == 0)[0]
    # As variantes sem gatilho preservam cada ID, vetor-base e rótulo original.
    base = x[targeted].copy()
    base[:, 4:] = 0
    t1, t2 = base.copy(), base.copy()
    t1[:, 4], t2[:, 5] = 1, 1
    plain, a, b = (linear_scores(model, v) for v in (base, t1, t2))
    metrics = {'clean': accuracy(y, clean), 'target_n': len(targeted),
               'plain_target': int(np.sum(plain >= .5)),
               'trigger1_target': int(np.sum(a >= .5)), 'trigger2_target': int(np.sum(b >= .5)),
               'trigger1_new_flips': int(np.sum((plain < .5) & (a >= .5))),
               'trigger2_new_flips': int(np.sum((plain < .5) & (b >= .5))),
               'eligible_clean_correct': int(np.sum(plain < .5))}
    predictions = {'clean': clean.tolist(), 'negative_ids': [rows[i]['id'] for i in targeted],
                   'plain': plain.tolist(), 'trigger1': a.tolist(), 'trigger2': b.tolist()}
    return metrics, predictions


def run(directory):
    out = new_output(directory)
    captures, results = [], []
    for seed in SEEDS:
        train, evaluation = data(seed, 'train', 400), data(seed + 1000, 'evaluation', 160)
        captures.append({'seed': seed, 'train': train, 'evaluation': evaluation})
        scenarios = [('clean', 0, train, [], [])]
        for budget in BUDGETS:
            for mode in ('random_labels', 'target', 'adaptive'):
                poisoned, changed = change(train, budget, mode, seed + 77)
                scenarios.append((mode, budget, poisoned, changed, []))
                if mode != 'random_labels':
                    kept, removed = quarantine(poisoned)
                    scenarios.append((mode + '_filtered', budget, kept, changed, removed))
        for mode, budget, rows, changed, removed in scenarios:
            model = fit(rows)
            metrics, predictions = evaluate(model, evaluation)
            key = f'{seed}_{mode}_{budget}'
            write(out / (key + '_model.json'), model)
            results.append({'id': key, 'seed': seed, 'mode': mode, 'budget': budget,
                            'fit_ids': [r['id'] for r in rows], 'fit_digest': digest(rows),
                            'modified_ids': changed, 'quarantined_ids': removed,
                            'clean_quarantined': len(set(removed) - set(changed)),
                            'modified_surviving': len(set(changed) - set(removed)),
                            'metrics': metrics, 'predictions': predictions})
    write(out / 'data.json', captures)
    write(out / 'results.json', results)
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory)
    integrity(out)
    datasets = {d['seed']: d for d in read(out / 'data.json')}
    results = read(out / 'results.json')
    assert set(datasets) == set(SEEDS) and len(results) == 48
    keys = set()
    for item in results:
        assert item['id'] not in keys
        keys.add(item['id'])
        dataset = datasets[item['seed']]
        assert len(dataset['train']) == 400 and len(dataset['evaluation']) == 160
        assert not ({r['id'] for r in dataset['train']} & {r['id'] for r in dataset['evaluation']})
        mode, budget = item['mode'], item['budget']
        original = dataset['train']
        if mode == 'clean':
            assert budget == 0
            rows, changed, removed = original, [], []
        else:
            assert budget in BUDGETS
            rows, changed = change(original, budget, mode.removesuffix('_filtered'), item['seed'] + 77)
            removed = []
            if mode.endswith('_filtered'):
                rows, removed = quarantine(rows)
        assert item['fit_ids'] == [r['id'] for r in rows] and item['fit_digest'] == digest(rows)
        assert item['modified_ids'] == changed and item['quarantined_ids'] == removed
        assert item['clean_quarantined'] == len(set(removed) - set(changed))
        assert item['modified_surviving'] == len(set(changed) - set(removed))
        metrics, predictions = evaluate(read(out / (item['id'] + '_model.json')), dataset['evaluation'])
        assert item['metrics'] == metrics
        assert item['predictions']['negative_ids'] == predictions['negative_ids']
        for field in ('clean', 'plain', 'trigger1', 'trigger2'):
            assert_close(item['predictions'][field], predictions[field])
        if mode == 'target_filtered':
            assert item['modified_surviving'] == 0
        if mode == 'adaptive_filtered':
            assert item['modified_surviving'] == budget
    expected = {f'{s}_clean_0' for s in SEEDS} | {
        f'{s}_{m}_{b}' for s in SEEDS for b in BUDGETS
        for m in ('random_labels', 'target', 'target_filtered', 'adaptive', 'adaptive_filtered')}
    assert keys == expected
    return {'lab': 'L22', 'verified': True, 'models_trained': len(results), 'seeds': list(SEEDS), 'budgets': list(BUDGETS)}
