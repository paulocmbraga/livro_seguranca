"""L23: perturbação válida, quantização, busca adaptada e treino aumentado reais."""
from itertools import product
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from .common import (new_output, write, read, seal, integrity, matrix, linear_export,
                     linear_scores, accuracy, assert_close)

BUDGETS = (0.0, .05, .15, .30)
METHODS = ('random9', 'finite_difference', 'adaptive_grid9', 'transfer')


def data(seed, prefix, count):
    rng = np.random.default_rng(seed)
    latent = rng.uniform(-1, 1, count)
    truth = latent > 0
    # Verdade vem do estado latente conservado; somente as duas leituras são mutáveis.
    x = np.column_stack([
        np.clip(.5 + .35 * latent + rng.normal(0, .07, count), 0, 1),
        np.clip(.5 + .30 * latent + rng.normal(0, .09, count), 0, 1),
        np.clip(.5 + .18 * latent + rng.normal(0, .17, count), 0, 1),
        rng.uniform(0, 1, count)])
    return [{'id': f'{prefix}-{i:03}', 'latent': float(latent[i]), 'x': row.tolist(), 'y': int(truth[i])}
            for i, row in enumerate(x)]


def transform(x, quantized):
    value = np.array(x, dtype=float, copy=True)
    if quantized:
        value[..., :2] = np.round(value[..., :2] * 10) / 10
    return value


def score(model, x, quantized=False):
    return linear_scores(model, transform(x, quantized))


def loss(y, probabilities):
    p = np.clip(probabilities, 1e-12, 1 - 1e-12)
    return -(np.asarray(y) * np.log(p) + (1 - np.asarray(y)) * np.log(1 - p))


def project(proposed, original, epsilon):
    original, proposed = np.asarray(original, dtype=float), np.array(proposed, dtype=float, copy=True)
    proposed[..., :2] = np.clip(proposed[..., :2], original[..., :2] - epsilon, original[..., :2] + epsilon)
    proposed[..., :2] = np.clip(proposed[..., :2], 0, 1)
    proposed[..., 2:] = original[..., 2:]
    return proposed


def valid(proposed, original, epsilon):
    a, b = np.asarray(proposed), np.asarray(original)
    return bool(np.isfinite(a).all() and (a >= 0).all() and (a <= 1).all()
                and np.array_equal(a[..., 2:], b[..., 2:])
                and np.max(np.abs(a[..., :2] - b[..., :2])) <= epsilon + 1e-10)


def fit(rows):
    x, y = matrix(rows)
    model = LogisticRegression(C=10, max_iter=1000, random_state=23).fit(x, y)
    exported = linear_export(model)
    assert_close(linear_scores(exported, x), model.predict_proba(x)[:, 1])
    return exported


def attack(model, original, y, epsilon, method, quantized, surrogate, seed=901):
    x, y = np.asarray(original), np.asarray(y)
    n = len(x)
    if method == 'finite_difference':
        h = 1e-6
        gradient = np.zeros_like(x)
        for axis in (0, 1):
            plus, minus = x.copy(), x.copy()
            plus[:, axis] = np.clip(plus[:, axis] + min(h, epsilon), 0, 1)
            minus[:, axis] = np.clip(minus[:, axis] - min(h, epsilon), 0, 1)
            gradient[:, axis] = (loss(y, score(model, plus, quantized)) - loss(y, score(model, minus, quantized))) / (2 * h)
        candidate = project(x + epsilon * np.sign(gradient), x, epsilon)
        candidates = [x, candidate]
        forward = 4 * n
    elif method == 'transfer':
        direction = (linear_scores(surrogate, x) - y)[:, None] * np.asarray(surrogate['coef'])
        candidates = [x, project(x + epsilon * np.sign(direction), x, epsilon)]
        forward = 0
    elif method in ('random9', 'adaptive_grid9'):
        if method == 'random9':
            offsets = np.random.default_rng(seed).uniform(-epsilon, epsilon, (8, n, 2))
            offsets = np.concatenate([np.zeros((1, n, 2)), offsets])
        else:
            offsets = np.asarray(list(product([-epsilon, 0, epsilon], repeat=2)))[:, None, :]
            offsets = np.repeat(offsets, n, axis=1)
        candidates = []
        for offset in offsets:
            candidate = x.copy()
            candidate[:, :2] += offset
            candidates.append(project(candidate, x, epsilon))
        forward = 0
    else:
        raise ValueError('method')
    losses = np.asarray([loss(y, score(model, c, quantized)) for c in candidates])
    forward += n * len(candidates)
    best = losses.argmax(axis=0)
    chosen = np.asarray(candidates)[best, np.arange(n)]
    return chosen, forward


def result_metrics(y, clean, attacked):
    correct = (np.asarray(clean) >= .5) == np.asarray(y)
    wrong = (np.asarray(attacked) >= .5) != np.asarray(y)
    return {'clean': accuracy(y, clean), 'adversarial': accuracy(y, attacked),
            'eligible': int(correct.sum()), 'new_errors': int(np.sum(correct & wrong)),
            'asr_on_initial_correct': float(np.sum(correct & wrong) / correct.sum()) if correct.any() else None}


def run(directory):
    out = new_output(directory)
    train, evaluation, surrogate_data = data(231, 'train', 400), data(232, 'evaluation', 120), data(233, 'surrogate', 200)
    baseline, surrogate = fit(train), fit(surrogate_data)
    x, y = matrix(train)
    direction = (linear_scores(baseline, x) - y)[:, None] * np.asarray(baseline['coef'])
    augmented_x = project(x + .15 * np.sign(direction), x, .15)
    augmented_rows = train + [dict(r, id='aug-' + r['id'], x=v.tolist()) for r, v in zip(train, augmented_x)]
    augmented = fit(augmented_rows)
    write(out / 'training_plan.json', {'augmentation_epsilon': .15, 'selected_before_evaluation': True,
                                      'selection': 'parâmetro fixado no código; sem seleção no conjunto final'})
    write(out / 'data.json', {'train': train, 'evaluation': evaluation, 'surrogate': surrogate_data})
    write(out / 'models.json', {'baseline': baseline, 'augmented': augmented, 'surrogate': surrogate})
    x, y = matrix(evaluation)
    rows = []
    for variant, model, quantized in [('plain', baseline, False), ('quantized', baseline, True), ('augmented', augmented, False)]:
        clean = score(model, x, quantized)
        for epsilon in BUDGETS:
            for method in METHODS:
                proposed, queries = attack(model, x, y, epsilon, method, quantized, surrogate)
                assert valid(proposed, x, epsilon)
                scores = score(model, proposed, quantized)
                rows.append({'variant': variant, 'epsilon': epsilon, 'method': method,
                             'forward_examples_in_search': queries, 'final_scoring_examples': len(x),
                             'valid_examples': len(x), 'x_adv': proposed.tolist(),
                             'clean_scores': clean.tolist(), 'scores': scores.tolist(),
                             'metrics': result_metrics(y, clean, scores)})
    write(out / 'results.json', rows)
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory)
    integrity(out)
    dataset, models = read(out / 'data.json'), read(out / 'models.json')
    assert tuple(len(dataset[k]) for k in ('train', 'evaluation', 'surrogate')) == (400, 120, 200)
    assert len({r['id'] for rows in dataset.values() for r in rows}) == 720
    assert read(out / 'training_plan.json') == {
        'augmentation_epsilon': .15, 'selected_before_evaluation': True,
        'selection': 'parâmetro fixado no código; sem seleção no conjunto final'}
    assert all(r['y'] == int(r['latent'] > 0) for rows in dataset.values() for r in rows)
    x, y = matrix(dataset['evaluation'])
    rows = read(out / 'results.json')
    assert len(rows) == 48
    keys = set()
    for r in rows:
        key = (r['variant'], r['epsilon'], r['method'])
        assert key not in keys
        keys.add(key)
        model = models['augmented' if r['variant'] == 'augmented' else 'baseline']
        quantized = r['variant'] == 'quantized'
        assert valid(r['x_adv'], x, r['epsilon'])
        assert r['valid_examples'] == r['final_scoring_examples'] == 120
        clean, attacked = score(model, x, quantized), score(model, r['x_adv'], quantized)
        assert_close(r['clean_scores'], clean)
        assert_close(r['scores'], attacked)
        assert r['metrics'] == result_metrics(y, clean, attacked)
        expected_queries = {'random9': 1080, 'adaptive_grid9': 1080, 'finite_difference': 720, 'transfer': 240}[r['method']]
        assert r['forward_examples_in_search'] == expected_queries
        if r['epsilon'] == 0:
            assert_close(r['x_adv'], x)
            assert r['metrics']['new_errors'] == 0
    assert keys == set(product(('plain', 'quantized', 'augmented'), BUDGETS, METHODS))
    return {'lab': 'L23', 'verified': True, 'models_trained': 3, 'curves': 48, 'evaluation_inputs': 120,
            'adversarial_variants_checked': 5760}
