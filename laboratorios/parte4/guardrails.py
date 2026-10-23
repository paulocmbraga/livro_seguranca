"""Classificador efetivamente treinado; propostas de ferramenta são preparadas."""
from collections import Counter
from importlib.metadata import version
import json
from pathlib import Path
import time

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from laboratorios.l09.campaign import make_corpus
from laboratorios.l09.services import Lab, records
from .common import PROJECT, new_output, write, seal, integrity


def train(rows):
    vec = TfidfVectorizer(analyzer='char', ngram_range=(3, 5), min_df=1,
                          max_features=6000, lowercase=True)
    x = vec.fit_transform([r['text'] for r in rows])
    clf = LogisticRegression(C=4, max_iter=500, random_state=17)
    clf.fit(x, [r['hostile'] for r in rows])
    return vec, clf


def metrics(rows, scores, threshold):
    c = Counter()
    for row, score in zip(rows, scores):
        truth, predicted = bool(row['hostile']), score >= threshold
        c[('tp' if predicted else 'fn') if truth else ('fp' if predicted else 'tn')] += 1
    return {k: c[k] for k in ('tp', 'fp', 'tn', 'fn')}


def select_threshold(rows, scores, candidates):
    table = [{'threshold': t, **metrics(rows, scores, t)} for t in candidates]
    chosen = min(table, key=lambda r: (2 * r['fn'] + r['fp'], -r['threshold']))
    return chosen['threshold'], table


def route(mode, score, threshold, review_slots):
    if mode == 'signal':
        return 'execute'
    if score is None:
        return 'hold_error'
    if score < threshold:
        return 'execute'
    if mode == 'block':
        return 'blocked'
    return 'review' if review_slots > 0 else 'hold_capacity'


def run(directory):
    out = new_output(directory)
    corpus = json.loads((PROJECT / 'materiais/parte4/detector.json').read_text(encoding='utf-8'))
    started = time.perf_counter()
    vec, clf = train(corpus['train'])
    train_seconds = time.perf_counter() - started
    cal_scores = clf.predict_proba(vec.transform([r['text'] for r in corpus['calibration']]))[:, 1]
    threshold, calibration = select_threshold(corpus['calibration'], cal_scores, corpus['thresholds'])
    # O limiar é escolhido e gravado antes de consumir o conjunto de avaliação.
    write(out / 'selection.json', {'threshold': threshold, 'criterion': 'min(2*FN+FP), maior limiar em empate',
                                  'calibration': calibration, 'train_seconds': train_seconds})
    write(out / 'model.json', {'vocabulary': {k:int(v) for k,v in vec.vocabulary_.items()}, 'idf': vec.idf_.tolist(),
                             'coefficients': clf.coef_.tolist(), 'intercept': clf.intercept_.tolist(),
                             'sklearn': version('scikit-learn'), 'classes': clf.classes_.tolist()})
    evaluation = corpus['evaluation']
    measured = []
    for row in evaluation:
        tick = time.perf_counter()
        score = float(clf.predict_proba(vec.transform([row['text']]))[0, 1])
        measured.append({'id': row['id'], 'score': score,
                         'seconds': time.perf_counter() - tick})
    write(out / 'scores.json', measured)
    results = []
    domain = make_corpus()
    with Lab(out / 'services', domain) as lab:
        for mode in ('negative', 'signal', 'block', 'review'):
            slots = 4
            for row, measured_row in zip(evaluation, measured):
                trace = mode + '_' + row['id']
                # Falha injetada no ponto do detector; não simula timeout de rede real.
                fault = mode != 'negative' and row['id'] == corpus['fault_case']
                score = None if fault else measured_row['score']
                decision = 'execute' if mode == 'negative' else route(mode, score, threshold, slots)
                review = None
                if decision == 'review':
                    slots -= 1
                    review = corpus['review_fixture'][row['id']]
                    decision = 'execute' if review == 'approve' else 'review_denied'
                status = None
                # Proposta é fixture independente do classificador. Não é uma geração de LLM.
                if decision == 'execute':
                    target = 'collector' if row['hostile'] else 'portal_alpha'
                    status, _ = lab.call('alpha', 'A' if mode == 'negative' else 'C', '/deliver',
                        {'case': trace, 'action': {'resource': 'alpha_contract', 'tenant': 'alpha',
                                                  'destination': target}})
                results.append({'trace': trace, 'id': row['id'], 'mode': mode, 'family': row['family'],
                                'hostile': row['hostile'], 'score': score, 'fault_injected': fault,
                                'decision': decision, 'review_fixture': review, 'status': status})
        # Chamada direta ao domínio ignora completamente o detector e o cliente habitual.
        direct, _ = lab.call('alpha', 'C', '/deliver', {'case': 'direct_bypass', 'action':
            {'resource': 'alpha_contract', 'tenant': 'alpha', 'destination': 'collector'}})
    receipts = records(out / 'services/destination.sqlite', 'receipts')
    events = records(out / 'services/domain.sqlite', 'events')
    write(out / 'receipts.json', receipts); write(out / 'events.json', events)
    write(out / 'results.json', {'lab': 'L13', 'threshold': threshold, 'rows': results,
        'direct_bypass_status': direct, 'classification': metrics(evaluation,
             [r['score'] for r in measured], threshold),
        'classification_by_family': {family: metrics(
            [r for r in evaluation if r['family'] == family],
            [s['score'] for r, s in zip(evaluation, measured) if r['family'] == family], threshold)
            for family in sorted({r['family'] for r in evaluation})},
        'detector_trained': True, 'llm_generation': False, 'human_review': 'prepared_fixture',
        'review_capacity_per_run': 4, 'train_seconds': train_seconds,
        'inference_seconds': sum(r['seconds'] for r in measured)})
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory); integrity(out)
    r = json.loads((out / 'results.json').read_text(encoding='utf-8'))
    receipts = records(out / 'services/destination.sqlite', 'receipts')
    events = records(out / 'services/domain.sqlite', 'events')
    assert receipts == json.loads((out / 'receipts.json').read_text(encoding='utf-8'))
    assert events == json.loads((out / 'events.json').read_text(encoding='utf-8'))
    data = json.loads((PROJECT / 'materiais/parte4/detector.json').read_text(encoding='utf-8'))
    scores = json.loads((out / 'scores.json').read_text(encoding='utf-8'))
    assert [s['id'] for s in scores] == [c['id'] for c in data['evaluation']]
    assert r['classification'] == metrics(data['evaluation'],[s['score'] for s in scores],r['threshold'])
    expected = {(mode, c['id']) for mode in ('negative', 'signal', 'block', 'review') for c in data['evaluation']}
    assert len(r['rows']) == len(expected) == 64
    assert {(x['mode'], x['id']) for x in r['rows']} == expected
    summary = {}
    for mode in ('negative', 'signal', 'block', 'review'):
        rows = [x for x in r['rows'] if x['mode'] == mode]
        for row in rows:
            observed = [x for x in receipts if x['case'] == row['trace']]
            assert len(observed) == int(row['status'] == 200)
            calls = [x for x in events if x['case'] == row['trace']]
            assert len(calls) == int(row['status'] is not None)
        summary[mode] = {'rows': len(rows), 'forbidden_receipts': sum(
            x['destination'] == 'collector' and x['case'].startswith(mode+'_') for x in receipts),
            'benign_success': sum(not x['hostile'] and x['status'] == 200 for x in rows),
            'reviewed': sum(x['review_fixture'] is not None for x in rows),
            'holds': sum(x['decision'].startswith('hold') for x in rows)}
    assert not [x for x in receipts if x['case'] == 'direct_bypass']
    assert r['direct_bypass_status'] == 403
    assert summary['negative']['forbidden_receipts'] == 8
    assert all(summary[m]['forbidden_receipts'] == 0 for m in ('signal', 'block', 'review'))
    return {'lab': 'L13', 'threshold': r['threshold'], 'classification': r['classification'],
            'summary': summary, 'receipts': len(receipts)}
