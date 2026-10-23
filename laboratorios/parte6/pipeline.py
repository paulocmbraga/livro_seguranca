"""L21: feature store com identidades HTTP e treino real separado da avaliação."""
from copy import deepcopy
import json
from pathlib import Path
import secrets

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from .common import (new_output, write, read, digest, seal, integrity, database,
                     serve, call, matrix, tree_export, tree_scores, accuracy, assert_close)


def corpus(seed=211):
    rng = np.random.default_rng(seed)
    rows = []
    for split, count in [('train', 160), ('calibration', 60), ('test', 80)]:
        for i in range(count):
            x = rng.uniform(0, 1, 6)
            y = int((x[0] > .45) != (x[1] > .55))
            if rng.random() < .12:
                y = 1 - y
            rows.append({'id': f'{split}-{i:03}', 'group': f'{split}-subject-{i:03}',
                         'split': split, 'origin': 'coleta_autorizada_v1', 'training_allowed': split != 'test',
                         'x': x.tolist(), 'y': y})
    return rows


def validate_training(rows, manifest):
    seen = set()
    for row in rows:
        reference = manifest.get(row['id'])
        if reference is None or reference['digest'] != digest(row):
            raise ValueError('provenance_mismatch')
        if reference['split'] != 'train' or not reference['training_allowed']:
            raise ValueError('split_not_training')
        if reference['group'] in seen:
            raise ValueError('duplicate_group')
        seen.add(reference['group'])
    if not seen:
        raise ValueError('empty_training')


class Store:
    def __init__(self, path, rows, strict=True):
        self.path, self.strict = Path(path), strict
        self.rows = {r['id']: r for r in rows}
        self.tokens = {name: secrets.token_hex(24) for name in ['trainer', 'evaluator', 'releaser']}
        self.jobs = {}
        with database(self.path) as db:
            db.executescript('CREATE TABLE reads(id INTEGER PRIMARY KEY,actor,ids,status);'
                             'CREATE TABLE promotions(id INTEGER PRIMARY KEY,actor,job,model_hash,report_hash);'
                             'CREATE TABLE requests(id INTEGER PRIMARY KEY,path,actor,status,reason);')

    def dispatch(self, path, headers, body):
        actor = next((a for a, t in self.tokens.items() if headers.get('Authorization') == 'Bearer ' + t), None)
        status, result = self.handle(path, actor, body)
        with database(self.path) as db:
            db.execute('INSERT INTO requests(path,actor,status,reason) VALUES(?,?,?,?)',
                       (path, actor, status, result.get('error', 'ok')))
        return status, result

    def handle(self, path, actor, body):
        if actor is None:
            return 401, {'error': 'identity'}
        if path == '/read':
            ids = body['ids']
            if not isinstance(ids, list) or len(ids) > 400 or any(i not in self.rows for i in ids):
                return 400, {'error': 'ids'}
            allowed = {'trainer': {'train', 'calibration'}, 'evaluator': {'test'}, 'releaser': set()}
            ok = not self.strict or all(self.rows[i]['split'] in allowed[actor] for i in ids)
            status = 200 if ok else 403
            with database(self.path) as db:
                db.execute('INSERT INTO reads(actor,ids,status) VALUES(?,?,?)', (actor, json.dumps(ids), status))
            return (200, {'rows': [self.rows[i] for i in ids]}) if ok else (403, {'error': 'split_policy'})
        if path == '/promote':
            if actor != 'releaser':
                return 403, {'error': 'promotion_role'}
            job = self.jobs.get(body.get('job'))
            if not job or not job['eligible']:
                return 409, {'error': 'ineligible_job'}
            if body.get('model_hash') != job['model_hash'] or body.get('report_hash') != job['report_hash']:
                return 409, {'error': 'artifact_changed'}
            with database(self.path) as db:
                rid = db.execute('INSERT INTO promotions(actor,job,model_hash,report_hash) VALUES(?,?,?,?)',
                    (actor, body['job'], job['model_hash'], job['report_hash'])).lastrowid
            return 200, {'receipt': rid}
        return 404, {'error': 'route'}


def run(directory):
    out = new_output(directory)
    rows = corpus()
    manifest = {r['id']: {k: r[k] for k in ('split', 'group', 'origin', 'training_allowed')} | {'digest': digest(r)} for r in rows}
    write(out / 'data.json', rows)
    write(out / 'data_manifest.json', manifest)
    strict, weak = Store(out / 'strict.sqlite', rows), Store(out / 'weak.sqlite', rows, False)
    attempts, events = [], []
    ids = {s: [r['id'] for r in rows if r['split'] == s] for s in ['train', 'calibration', 'test']}
    def record(name, status, body):
        attempts.append({'case': name, 'status': status, 'reason': body.get('error', 'ok')})
        return body
    with serve(strict.dispatch) as url, serve(weak.dispatch) as weak_url:
        train = record('read_train', *call(url + '/read', strict.tokens['trainer'], {'ids': ids['train']}))['rows']
        calibration = record('read_calibration', *call(url + '/read', strict.tokens['trainer'], {'ids': ids['calibration']}))['rows']
        record('trainer_test', *call(url + '/read', strict.tokens['trainer'], {'ids': ids['test']}))
        record('forged_split', *call(url + '/read', strict.tokens['trainer'], {'ids': ids['test'], 'split': 'train', 'role': 'evaluator'}))
        record('unknown_identity', *call(url + '/read', 'invalid', {'ids': ids['train']}))
        validate_training(train, manifest)
        x, y = matrix(train)
        cx, cy = matrix(calibration)
        candidates = []
        models = []
        for depth in [2, 4, 8, None]:
            model = DecisionTreeClassifier(max_depth=depth, random_state=21).fit(x, y)
            scores = model.predict_proba(cx)[:, 1]
            candidates.append({'max_depth': depth, **accuracy(cy, scores)})
            models.append(model)
        selected = max(range(4), key=lambda i: (candidates[i]['correct'], -i))
        write(out / 'candidate_models.json', [tree_export(m) for m in models])
        clean_model = tree_export(models[selected])
        assert_close(tree_scores(clean_model, cx), models[selected].predict_proba(cx)[:, 1])
        selection = {'criterion': 'maior acerto na calibração; menor complexidade em empate',
                     'candidates': candidates, 'selected': selected, 'fit_ids': ids['train'],
                     'selection_ids': ids['calibration'], 'test_used_for_selection': False}
        write(out / 'selection.json', selection)
        events.append({'step': 1, 'event': 'selection_frozen', 'digest': digest(selection)})
        evaluation = record('evaluator_test', *call(url + '/read', strict.tokens['evaluator'], {'ids': ids['test']}))['rows']
        events.append({'step': 2, 'event': 'test_opened', 'identity': 'evaluator'})
        leaked = record('weak_trainer_test', *call(weak_url + '/read', weak.tokens['trainer'], {'ids': ids['test']}))['rows']
        attempts_local = []
        for name, proposed in [('test_in_train', train + leaked),
                               ('forged_origin', [dict(train[0], origin='outra_origem')] + train[1:]),
                               ('forged_id', [dict(leaked[0], id='train-invented', split='train')] + train),
                               ('duplicate_group', train + [deepcopy(train[0])])]:
            try:
                validate_training(proposed, manifest)
                raise AssertionError('controle deveria recusar')
            except ValueError as error:
                attempts_local.append({'case': name, 'reason': str(error)})
        lx, ly = matrix(train + leaked)
        leaky = DecisionTreeClassifier(max_depth=candidates[selected]['max_depth'], random_state=21).fit(lx, ly)
        leaky_model = tree_export(leaky)
        tx, ty = matrix(evaluation)
        predictions = [{'id': r['id'], 'y': r['y'], 'clean': float(a), 'leaky': float(b)}
                       for r, a, b in zip(evaluation, tree_scores(clean_model, tx), tree_scores(leaky_model, tx))]
        report = {'clean': accuracy(ty, [p['clean'] for p in predictions]),
                  'leaky': accuracy(ty, [p['leaky'] for p in predictions]),
                  'clean_test_overlap': 0, 'leaky_test_overlap': len(leaked)}
        strict.jobs['clean'] = {'eligible': True, 'model_hash': digest(clean_model), 'report_hash': digest(report)}
        strict.jobs['leaky'] = {'eligible': False, 'model_hash': digest(leaky_model), 'report_hash': digest(report)}
        valid = {'job': 'clean', 'model_hash': digest(clean_model), 'report_hash': digest(report)}
        record('trainer_promote', *call(url + '/promote', strict.tokens['trainer'], valid))
        record('changed_model', *call(url + '/promote', strict.tokens['releaser'], dict(valid, model_hash='alterado')))
        record('leaky_promote', *call(url + '/promote', strict.tokens['releaser'], dict(valid, job='leaky')))
        record('valid_promote', *call(url + '/promote', strict.tokens['releaser'], valid))
    write(out / 'clean_model.json', clean_model)
    write(out / 'leaky_model.json', leaky_model)
    write(out / 'predictions.json', predictions)
    write(out / 'events.json', events)
    write(out / 'results.json', {'metrics': report, 'http': attempts, 'local_gate': attempts_local,
          'leaky_fit_ids': ids['train'] + ids['test'], 'jobs': strict.jobs})
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory)
    integrity(out)
    rows, manifest = read(out / 'data.json'), read(out / 'data_manifest.json')
    assert len(rows) == 300 and len(manifest) == 300
    assert len({r['id'] for r in rows}) == len({r['group'] for r in rows}) == 300
    for row in rows:
        assert manifest[row['id']]['digest'] == digest(row)
    train = [r for r in rows if r['split'] == 'train']
    calibration = [r for r in rows if r['split'] == 'calibration']
    test = [r for r in rows if r['split'] == 'test']
    assert (len(train), len(calibration), len(test)) == (160, 60, 80)
    validate_training(train, manifest)
    s, r = read(out / 'selection.json'), read(out / 'results.json')
    assert set(s['fit_ids']) == {x['id'] for x in train}
    assert set(s['selection_ids']) == {x['id'] for x in calibration}
    assert s['selected'] == max(range(4), key=lambda i: (s['candidates'][i]['correct'], -i))
    candidate_models = read(out / 'candidate_models.json')
    cx, cy = matrix(calibration)
    assert len(candidate_models) == 4
    for model, candidate in zip(candidate_models, s['candidates']):
        assert {k: candidate[k] for k in ('n', 'correct', 'accuracy')} == accuracy(cy, tree_scores(model, cx))
    assert candidate_models[s['selected']] == read(out / 'clean_model.json')
    assert not s['test_used_for_selection']
    assert read(out / 'events.json') == [{'step': 1, 'event': 'selection_frozen', 'digest': digest(s)},
                                        {'step': 2, 'event': 'test_opened', 'identity': 'evaluator'}]
    predictions = read(out / 'predictions.json')
    assert [p['id'] for p in predictions] == [row['id'] for row in test]
    assert [p['y'] for p in predictions] == [row['y'] for row in test]
    x, y = matrix(test)
    for name in ['clean', 'leaky']:
        scores = tree_scores(read(out / (name + '_model.json')), x)
        assert_close(scores, [p[name] for p in predictions])
        assert r['metrics'][name] == accuracy(y, scores)
    assert r['metrics']['clean_test_overlap'] == 0 and r['metrics']['leaky_test_overlap'] == 80
    assert set(r['leaky_fit_ids']) & {t['id'] for t in test} == {t['id'] for t in test}
    expected = {'read_train': 200, 'read_calibration': 200, 'trainer_test': 403, 'forged_split': 403,
                'unknown_identity': 401, 'evaluator_test': 200, 'weak_trainer_test': 200,
                'trainer_promote': 403, 'changed_model': 409, 'leaky_promote': 409, 'valid_promote': 200}
    assert {a['case']: a['status'] for a in r['http']} == expected and len(r['http']) == 11
    assert len(r['local_gate']) == 4
    with database(out / 'strict.sqlite') as db:
        assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 10
        receipts = db.execute('SELECT actor,job,model_hash,report_hash FROM promotions').fetchall()
        assert receipts == [('releaser', 'clean', digest(read(out / 'clean_model.json')), digest(r['metrics']))]
        assert db.execute("SELECT count(*) FROM reads WHERE actor='trainer' AND status=403").fetchone()[0] == 2
    with database(out / 'weak.sqlite') as db:
        assert db.execute('SELECT count(*) FROM reads WHERE status=200').fetchone()[0] == 1
    return {'lab': 'L21', 'verified': True, 'http_requests': 11, 'records': 300, **r['metrics']}
