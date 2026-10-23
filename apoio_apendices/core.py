"""Integridade, denominadores, reconciliação e impacto com biblioteca padrão."""
from datetime import date
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate_key')
            out[key] = value
        return out

    def nonfinite(value):
        raise ValueError('nonfinite_json')
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('nonfinite_json')
        return parsed
    return json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite,
                      parse_float=finite_float)


def fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('fields')


def label(value):
    if type(value) is not str or not value.strip():
        raise ValueError('label')
    return value


def safe_path(root, name):
    label(name)
    path = PurePosixPath(name)
    if (path.is_absolute() or ':' in name or '\\' in name or
            any(p in ('', '.', '..') or p != p.rstrip(' .') for p in name.split('/'))):
        raise ValueError('path')
    root = Path(root).resolve()
    current = root
    for component in path.parts:
        current = current / component
        if current.is_symlink() or current.is_junction():
            raise ValueError('link')
    if not current.resolve().is_relative_to(root):
        raise ValueError('escape')
    return current


def verify_files(root, entries):
    """Confere uma allowlist. Não assina, autentica nem julga significado."""
    if type(entries) is not list or not entries:
        raise ValueError('empty_manifest')
    seen = set()
    checked = []
    for entry in entries:
        fields(entry, ('path', 'sha256', 'bytes'))
        name = label(entry['path'])
        if name.casefold() in seen:
            raise ValueError('duplicate_path')
        seen.add(name.casefold())
        if type(entry['bytes']) is not int or not 0 <= entry['bytes'] <= 8_388_608:
            raise ValueError('size')
        if type(entry['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', entry['sha256']):
            raise ValueError('sha256')
        path = safe_path(root, name)
        if not path.is_file():
            raise ValueError('missing')
        if path.stat().st_size != entry['bytes']:
            raise ValueError('size_mismatch')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('hash_mismatch')
        checked.append(name)
    return checked


def counts(rows):
    """Limites identificados por observação incompleta, não intervalo de confiança."""
    if type(rows) is not list:
        raise ValueError('rows')
    seen = set()
    attacks, legitimate = [], []
    for row in rows:
        fields(row, ('case', 'family', 'legitimate', 'effect'))
        case = label(row['case'])
        label(row['family'])
        if case in seen:
            raise ValueError('duplicate_case')
        seen.add(case)
        if type(row['legitimate']) is not bool:
            raise ValueError('legitimate')
        if row['effect'] not in ('authorized', 'unauthorized', 'absent', 'unknown'):
            raise ValueError('effect')
        (legitimate if row['legitimate'] else attacks).append(row)
    n = len(attacks)
    k = sum(r['effect'] == 'unauthorized' for r in attacks)
    unknown = sum(r['effect'] == 'unknown' for r in attacks)
    good = sum(r['effect'] == 'authorized' for r in legitimate)
    return {'attack_n': n, 'unauthorized': k, 'unknown': unknown,
            'identified_bounds': [k / n, (k + unknown) / n] if n else None,
            'legitimate_n': len(legitimate), 'legitimate_completed': good,
            'legitimate_unknown': sum(r['effect'] == 'unknown' for r in legitimate),
            'families': len({r['family'] for r in attacks})}


def wilson(successes, total, z=1.959963984540054):
    if (type(successes) is not int or type(total) is not int or
            total <= 0 or not 0 <= successes <= total or
            type(z) not in (int, float) or not math.isfinite(z) or z <= 0 or
            not math.isfinite(z * z)):
        raise ValueError('binomial_input')
    p = successes / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return max(0., center - half), min(1., center + half)


def reconcile(plans, receipts, audits):
    """Reconcilia registros preparados. Ausência exige auditoria completa explícita."""
    if any(type(x) is not list for x in (plans, receipts, audits)):
        raise ValueError('records')
    intended, by_id, by_operation, observed = {}, {}, {}, {}
    for p in plans:
        fields(p, ('operation', 'action_digest'))
        op = label(p['operation'])
        label(p['action_digest'])
        if op in intended:
            raise ValueError('duplicate_operation')
        intended[op] = p['action_digest']
    for receipt in receipts:
        fields(receipt, ('receipt', 'operation', 'action_digest'))
        rid, op = label(receipt['receipt']), label(receipt['operation'])
        if op not in intended or receipt['action_digest'] != intended[op]:
            raise ValueError('receipt_binding')
        if rid in by_id and by_id[rid] != receipt:
            raise ValueError('receipt_conflict')
        if op in by_operation and by_operation[op] != rid:
            raise ValueError('multiple_effects')
        by_id[rid], by_operation[op] = receipt, rid
    for audit in audits:
        fields(audit, ('operation', 'state'))
        op = audit['operation']
        if op not in intended or op in observed or audit['state'] not in ('complete_absent', 'unavailable'):
            raise ValueError('audit')
        if op in by_operation and audit['state'] == 'complete_absent':
            raise ValueError('contradictory_evidence')
        observed[op] = audit['state']
    return {op: {'state': 'confirmed' if op in by_operation else
                 'absent' if observed.get(op) == 'complete_absent' else 'unknown',
                 'receipt': by_operation.get(op)} for op in sorted(intended)}


def reference_key(record):
    fields(record, ('project', 'edition', 'locator', 'consulted', 'kind'))
    for value in record.values():
        label(value)
    date.fromisoformat(record['consulted'])
    if record['kind'] not in ('list', 'guide', 'taxonomy', 'standard', 'protocol', 'catalog'):
        raise ValueError('reference_kind')
    return tuple(record[k] for k in ('project', 'edition', 'locator'))


def impact(before, after, dependencies):
    """Alcance transitivo num grafo declarado; não descobre dependências ausentes."""
    if any(type(x) is not dict for x in (before, after, dependencies)):
        raise ValueError('graph')
    nodes = set(before) | set(after)
    for key, value in list(before.items()) + list(after.items()):
        label(key)
        label(value)
    if set(dependencies) != nodes:
        raise ValueError('graph_coverage')
    for key, values in dependencies.items():
        if type(values) is not list or any(type(v) is not str for v in values):
            raise ValueError('dependency')
        if len(values) != len(set(values)) or not set(values) <= nodes:
            raise ValueError('dependency')
    changed = {n for n in nodes if before.get(n) != after.get(n)}
    affected = set(changed)
    while True:
        enlarged = affected | {n for n, deps in dependencies.items() if set(deps) & affected}
        if enlarged == affected:
            break
        affected = enlarged
    return {'changed': sorted(changed), 'requalify': sorted(affected),
            'decision': 'new_evidence_required' if changed else 'no_declared_change',
            'automatic_production_approval': False}
