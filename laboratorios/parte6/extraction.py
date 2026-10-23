"""L24: extração limitada exclusivamente de um modelo próprio por HTTP local."""
import json
from pathlib import Path
import secrets

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from .common import (new_output, write, read, seal, integrity, matrix, tree_export,
                     tree_scores, accuracy, assert_close, database, serve, call)

BUDGETS = (16, 64, 128)
PROFILES = ('labels', 'scores', 'limited_labels', 'limited_scores')


def data(seed, prefix, count):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0, 1, (count, 3))
    y = x[:, 0] * x[:, 1] + .6 * np.sin(3 * x[:, 2]) > .65
    return [{'id': f'{prefix}-{i:03}', 'x': row.tolist(), 'y': int(y[i])} for i, row in enumerate(x)]


def forest_scores(model, x):
    return np.mean([tree_scores(t, x) for t in model['trees']], axis=0)


def fidelity(reference, candidate):
    a, b = np.asarray(reference) >= .5, np.asarray(candidate) >= .5
    return {'n': len(a), 'agreements': int(np.sum(a == b)), 'fidelity': float(np.mean(a == b))}


class PredictionAPI:
    def __init__(self, path, model, profile):
        if profile not in PROFILES:
            raise ValueError('profile')
        self.path, self.model, self.profile = Path(path), model, profile
        self.tokens = {name: secrets.token_hex(24) for name in ('attacker_a', 'attacker_b', 'legitimate_alpha', 'legitimate_beta')}
        self.organizations = {'attacker_a': 'alpha', 'attacker_b': 'alpha', 'legitimate_alpha': 'alpha', 'legitimate_beta': 'beta'}
        with database(path) as db:
            db.executescript('CREATE TABLE usage(organization PRIMARY KEY,used INTEGER);'
                             'CREATE TABLE requests(id INTEGER PRIMARY KEY,actor,organization,status,x,response);'
                             'CREATE TABLE receipts(id INTEGER PRIMARY KEY,actor,organization,x,score,label);')

    def dispatch(self, path, headers, body):
        actor = next((a for a, t in self.tokens.items() if headers.get('Authorization') == 'Bearer ' + t), None)
        organization = self.organizations.get(actor)
        status, response = self.handle(path, actor, organization, body)
        with database(self.path) as db:
            db.execute('INSERT INTO requests(actor,organization,status,x,response) VALUES(?,?,?,?,?)',
                (actor, organization, status, json.dumps(body.get('x')), json.dumps(response)))
        return status, response

    def handle(self, path, actor, organization, body):
        if path != '/predict':
            return 404, {'error': 'route'}
        if actor is None:
            return 401, {'error': 'identity'}
        x = np.asarray(body.get('x'), dtype=float)
        if x.shape != (3,) or not np.isfinite(x).all() or (x < 0).any() or (x > 1).any():
            return 400, {'error': 'input_contract'}
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO usage VALUES(?,0)', (organization,))
            used = db.execute('SELECT used FROM usage WHERE organization=?', (organization,)).fetchone()[0]
            if self.profile.startswith('limited') and used >= 32:
                return 429, {'error': 'organization_budget'}
            score = float(self.model.predict_proba(x[None, :])[0, 1])
            label = int(score >= .5)
            rid = db.execute('INSERT INTO receipts(actor,organization,x,score,label) VALUES(?,?,?,?,?)',
                (actor, organization, json.dumps(x.tolist()), score, label)).lastrowid
            db.execute('UPDATE usage SET used=used+1 WHERE organization=?', (organization,))
        response = {'receipt': rid, 'label': label}
        if self.profile.endswith('scores'):
            response['score'] = score
        return 200, response


def run(directory):
    out = new_output(directory)
    train, queries, evaluation = data(241, 'victim_train', 600), data(242, 'query', 128), data(243, 'evaluation', 400)
    legitimate = data(244, 'legitimate', 8)
    x, y = matrix(train)
    victim = RandomForestClassifier(n_estimators=25, max_depth=6, min_samples_leaf=2, random_state=24, n_jobs=1).fit(x, y)
    exported = {'kind': 'forest', 'trees': [tree_export(t) for t in victim.estimators_]}
    ex, ey = matrix(evaluation)
    reference = victim.predict_proba(ex)[:, 1]
    assert_close(forest_scores(exported, ex), reference)
    write(out / 'victim_model.json', exported)
    write(out / 'data.json', {'train': train, 'queries': queries, 'evaluation': evaluation, 'legitimate': legitimate})
    write(out / 'reference.json', {'scores': reference.tolist(), 'accuracy': accuracy(ey, reference)})
    results = []
    for profile in PROFILES:
        for budget in BUDGETS:
            key = f'{profile}_{budget}'
            api = PredictionAPI(out / (key + '.sqlite'), victim, profile)
            observations, legitimate_results, checks = [], [], []
            with serve(api.dispatch) as url:
                for i, row in enumerate(queries[:budget]):
                    actor = 'attacker_a' if i % 2 == 0 else 'attacker_b'
                    # Metadados falsos não alteram a organização autenticada.
                    status, body = call(url + '/predict', api.tokens[actor], {'x': row['x'], 'tenant': 'beta', 'role': 'admin'})
                    observations.append({'id': row['id'], 'actor': actor, 'status': status, 'response': body})
                for actor in ('legitimate_alpha', 'legitimate_beta'):
                    for row in legitimate:
                        status, body = call(url + '/predict', api.tokens[actor], {'x': row['x']})
                        legitimate_results.append({'actor': actor, 'id': row['id'], 'status': status, 'response': body})
                for name, token, payload in [('unknown_identity', 'invalid', {'x': [0, 0, 0]}),
                                             ('invalid_vector', api.tokens['attacker_a'], {'x': [2, 0, 0]})]:
                    status, body = call(url + '/predict', token, payload)
                    checks.append({'case': name, 'status': status, 'response': body})
            accepted = [r for r in observations if r['status'] == 200]
            qmap = {r['id']: r['x'] for r in queries}
            qx = np.asarray([qmap[r['id']] for r in accepted])
            qy = np.asarray([r['response']['label'] for r in accepted])
            if profile.endswith('scores'):
                targets = [r['response']['score'] for r in accepted]
                surrogate = DecisionTreeRegressor(max_depth=5, min_samples_leaf=2, random_state=24).fit(qx, targets)
                predicted = surrogate.predict(ex)
            else:
                surrogate = DecisionTreeClassifier(max_depth=5, min_samples_leaf=2, random_state=24).fit(qx, qy)
                predicted = surrogate.predict_proba(ex)[:, list(surrogate.classes_).index(1)] if 1 in surrogate.classes_ else np.zeros(len(ex))
            numerical = tree_export(surrogate)
            assert_close(tree_scores(numerical, ex), predicted)
            write(out / (key + '_surrogate.json'), numerical)
            majority = int(qy.mean() >= .5)
            record = {'id': key, 'profile': profile, 'budget_requested': budget,
                      'accepted_queries': len(accepted), 'rejected_queries': budget - len(accepted),
                      'cost_units': len(accepted), 'observations': observations,
                      'legitimate': legitimate_results, 'checks': checks,
                      'predictions': predicted.tolist(), 'fidelity': fidelity(reference, predicted),
                      'ground_truth_accuracy': accuracy(ey, predicted),
                      'majority_baseline': fidelity(reference, np.full(len(ex), majority)),
                      'majority_label': majority,
                      'legitimate_accepted': {a: sum(r['status'] == 200 and r['actor'] == a for r in legitimate_results)
                                               for a in ('legitimate_alpha', 'legitimate_beta')}}
            results.append(record)
    write(out / 'results.json', results)
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory)
    integrity(out)
    dataset, records, reference = read(out / 'data.json'), read(out / 'results.json'), read(out / 'reference.json')
    assert tuple(len(dataset[k]) for k in ('train', 'queries', 'evaluation', 'legitimate')) == (600, 128, 400, 8)
    assert len({r['id'] for rows in dataset.values() for r in rows}) == 1136
    x, y = matrix(dataset['evaluation'])
    victim = read(out / 'victim_model.json')
    scores = forest_scores(victim, x)
    assert_close(reference['scores'], scores)
    assert reference['accuracy'] == accuracy(y, scores)
    assert len(records) == 12
    assert {r['id'] for r in records} == {f'{p}_{b}' for p in PROFILES for b in BUDGETS}
    total_requests = total_receipts = 0
    for r in records:
        limited = r['profile'].startswith('limited')
        budget = r['budget_requested']
        accepted = min(32, budget) if limited else budget
        assert r['accepted_queries'] == r['cost_units'] == accepted
        assert r['rejected_queries'] == budget - accepted
        assert len(r['observations']) == budget and len(r['legitimate']) == 16
        assert [o['id'] for o in r['observations']] == [q['id'] for q in dataset['queries'][:budget]]
        for i, obs in enumerate(r['observations']):
            assert obs['status'] == (200 if i < accepted else 429)
            if obs['status'] == 200:
                qs = float(forest_scores(victim, [dataset['queries'][i]['x']])[0])
                assert obs['response']['label'] == int(qs >= .5)
                assert ('score' in obs['response']) == r['profile'].endswith('scores')
                if 'score' in obs['response']:
                    assert_close(obs['response']['score'], qs)
        predictions = tree_scores(read(out / (r['id'] + '_surrogate.json')), x)
        assert_close(r['predictions'], predictions)
        assert r['fidelity'] == fidelity(scores, predictions)
        assert r['ground_truth_accuracy'] == accuracy(y, predictions)
        labels = [o['response']['label'] for o in r['observations'] if o['status'] == 200]
        majority = int(np.mean(labels) >= .5)
        assert r['majority_label'] == majority
        assert r['majority_baseline'] == fidelity(scores, np.full(len(x), majority))
        expected_legit = {'legitimate_alpha': min(8, 32 - accepted) if limited else 8, 'legitimate_beta': 8}
        assert r['legitimate_accepted'] == expected_legit
        assert {c['case']: c['status'] for c in r['checks']} == {'unknown_identity': 401, 'invalid_vector': 400}
        with database(out / (r['id'] + '.sqlite')) as db:
            count = db.execute('SELECT count(*) FROM requests').fetchone()[0]
            receipts = db.execute('SELECT id,actor,organization,x,score,label FROM receipts ORDER BY id').fetchall()
            assert count == budget + 18
            assert len(receipts) == accepted + sum(expected_legit.values())
            assert db.execute("SELECT count(*) FROM receipts WHERE actor LIKE 'attacker%' AND organization!='alpha'").fetchone()[0] == 0
            for _, actor, org, raw, actual_score, label in receipts:
                assert org == ('beta' if actor == 'legitimate_beta' else 'alpha')
                assert_close(actual_score, forest_scores(victim, [json.loads(raw)])[0])
                assert label == int(actual_score >= .5)
            for org, used in db.execute('SELECT organization,used FROM usage'):
                assert used == sum(item[2] == org for item in receipts)
                assert not limited or used <= 32
            # Cada sucesso recebido deve apontar para um recibo efetivo único.
            responses = [o['response']['receipt'] for o in r['observations'] + r['legitimate'] if o['status'] == 200]
            assert sorted(responses) == [receipt[0] for receipt in receipts]
            total_requests += count
            total_receipts += len(receipts)
    assert total_requests == 1048 and total_receipts == 736
    return {'lab': 'L24', 'verified': True, 'victim_models': 1, 'surrogates': 12,
            'http_requests': total_requests, 'inferences': total_receipts, 'extraction_queries_admitted': 576}
