import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from apoio_apendices.core import counts, impact, reconcile, reference_key, strict_json, verify_files, wilson
from apoio_apendices.__main__ import compute, fixture


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'a.txt').write_bytes(b'abc')
        self.entry = {'path': 'a.txt', 'sha256': hashlib.sha256(b'abc').hexdigest(), 'bytes': 3}

    def test_valid(self):
        self.assertEqual(verify_files(self.root, [self.entry]), ['a.txt'])

    def test_changed_same_size(self):
        (self.root / 'a.txt').write_bytes(b'abd')
        with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
            verify_files(self.root, [self.entry])

    def test_changed_size(self):
        (self.root / 'a.txt').write_bytes(b'abcd')
        with self.assertRaisesRegex(ValueError, 'size_mismatch'):
            verify_files(self.root, [self.entry])

    def test_missing(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            verify_files(self.root, [{**self.entry, 'path': 'missing'}])

    def test_escape_and_windows_paths(self):
        for name in ('../a.txt', '/a.txt', 'C:/a.txt', 'a\\b', 'a/../b', './a.txt', 'a//b', 'a.txt.', 'a.txt ', 'dir./a.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_files(self.root, [{**self.entry, 'path': name}])

    def test_duplicate_casefold_path(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_path'):
            verify_files(self.root, [self.entry, {**self.entry, 'path': 'A.txt'}])

    def test_boolean_size(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            verify_files(self.root, [{**self.entry, 'bytes': True}])

    def test_size_budget(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            verify_files(self.root, [{**self.entry, 'bytes': 8_388_609}])

    def test_unknown_field(self):
        with self.assertRaisesRegex(ValueError, 'fields'):
            verify_files(self.root, [{**self.entry, 'approved': True}])

    def test_empty_inventory(self):
        with self.assertRaisesRegex(ValueError, 'empty_manifest'):
            verify_files(self.root, [])

    def test_invalid_digest(self):
        with self.assertRaisesRegex(ValueError, 'sha256'):
            verify_files(self.root, [{**self.entry, 'sha256': 'not-a-hash'}])


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.rows = fixture()['cases']

    def test_bounds_preserve_unknown(self):
        result = counts(self.rows)
        self.assertEqual(result['identified_bounds'], [0.25, 0.5])
        self.assertEqual(result['legitimate_n'], 2)
        self.assertEqual(result['legitimate_completed'], 1)
        self.assertEqual(result['legitimate_unknown'], 1)

    def test_no_denominator(self):
        self.assertIsNone(counts([])['identified_bounds'])

    def test_duplicate_case(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_case'):
            counts(self.rows + [self.rows[0]])

    def test_no_truthy_integer(self):
        self.rows[0]['legitimate'] = 1
        with self.assertRaisesRegex(ValueError, 'legitimate'):
            counts(self.rows)

    def test_unknown_effect(self):
        self.rows[0]['effect'] = 'probably_blocked'
        with self.assertRaisesRegex(ValueError, 'effect'):
            counts(self.rows)

    def test_family_is_not_case_count(self):
        result = counts(self.rows)
        self.assertEqual(result['attack_n'], 4)
        self.assertEqual(result['families'], 2)

    def test_zero_wilson_not_zero_uncertainty(self):
        lo, hi = wilson(0, 20)
        self.assertAlmostEqual(lo, 0.)
        self.assertGreater(hi, 0.16)
        self.assertLess(hi, 0.17)

    def test_wilson_symmetry(self):
        lo, hi = wilson(7, 20)
        rlo, rhi = wilson(13, 20)
        self.assertAlmostEqual(lo, 1 - rhi)
        self.assertAlmostEqual(hi, 1 - rlo)

    def test_invalid_binomial_inputs(self):
        for args in ((0, 0), (1, 0), (21, 20), (-1, 20), (True, 20), (1, 20, float('nan')), (1, 20, 1e308)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                wilson(*args)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        f = fixture()
        self.p, self.r, self.a = f['plans'], f['receipts'], f['audits']

    def test_retry_and_missing_observation(self):
        result = reconcile(self.p, self.r, self.a)
        self.assertEqual(result['op1'], {'state': 'confirmed', 'receipt': 'r1'})
        self.assertEqual(result['op2']['state'], 'unknown')
        self.assertEqual(result['op3']['state'], 'absent')

    def test_missing_audit_is_unknown(self):
        self.assertEqual(reconcile(self.p, [], [])['op1']['state'], 'unknown')

    def test_receipt_wrong_action(self):
        self.r[0]['action_digest'] = 'other'
        with self.assertRaisesRegex(ValueError, 'receipt_binding'):
            reconcile(self.p, self.r, self.a)

    def test_unplanned_receipt(self):
        self.r[0]['operation'] = 'outside'
        with self.assertRaisesRegex(ValueError, 'receipt_binding'):
            reconcile(self.p, self.r, self.a)

    def test_two_effects_same_operation(self):
        self.r[1]['receipt'] = 'r2'
        with self.assertRaisesRegex(ValueError, 'multiple_effects'):
            reconcile(self.p, self.r, self.a)

    def test_receipt_id_reused_for_other_operation(self):
        self.r.append({'receipt': 'r1', 'operation': 'op2', 'action_digest': 'synthetic-action-2'})
        with self.assertRaisesRegex(ValueError, 'receipt_conflict'):
            reconcile(self.p, self.r, self.a)

    def test_contradiction_is_not_silently_resolved(self):
        self.a.append({'operation': 'op1', 'state': 'complete_absent'})
        with self.assertRaisesRegex(ValueError, 'contradictory_evidence'):
            reconcile(self.p, self.r, self.a)

    def test_audit_duplicate(self):
        self.a.append(self.a[0])
        with self.assertRaisesRegex(ValueError, 'audit'):
            reconcile(self.p, self.r, self.a)

    def test_plan_duplicate(self):
        self.p.append(self.p[0])
        with self.assertRaisesRegex(ValueError, 'duplicate_operation'):
            reconcile(self.p, self.r, self.a)


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture()

    def test_transitive_change(self):
        f = self.f
        result = impact(f['before'], f['after'], f['dependencies'])
        self.assertEqual(result['requalify'], ['delivery', 'prompt', 'response'])
        self.assertFalse(result['automatic_production_approval'])

    def test_no_change_is_not_approval(self):
        f = self.f
        result = impact(f['before'], f['before'], f['dependencies'])
        self.assertEqual(result['requalify'], [])
        self.assertFalse(result['automatic_production_approval'])

    def test_removed_component(self):
        f = self.f
        after = dict(f['before'])
        del after['model']
        self.assertEqual(impact(f['before'], after, f['dependencies'])['requalify'], ['delivery', 'model', 'response'])

    def test_cycles_terminate(self):
        result = impact({'a': '1', 'b': '1'}, {'a': '2', 'b': '1'}, {'a': ['b'], 'b': ['a']})
        self.assertEqual(result['requalify'], ['a', 'b'])

    def test_missing_component_in_graph(self):
        with self.assertRaisesRegex(ValueError, 'graph_coverage'):
            impact({'a': '1'}, {'a': '2'}, {})

    def test_unlisted_dependency(self):
        with self.assertRaisesRegex(ValueError, 'dependency'):
            impact({'a': '1'}, {'a': '2'}, {'a': ['missing']})

    def test_reference_version_is_part_of_key(self):
        a, b = self.f['references']
        self.assertNotEqual(reference_key(a), reference_key(b))

    def test_invalid_date(self):
        bad = {**self.f['references'][0], 'consulted': 'yesterday'}
        with self.assertRaises(ValueError):
            reference_key(bad)


class EncodingTests(unittest.TestCase):
    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_key'):
            strict_json('{"owner":"alpha","owner":"beta"}')

    def test_nonfinite_rejected(self):
        for token in ('NaN', 'Infinity', '-Infinity', '1e400', '-1e400'):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, 'nonfinite_json'):
                strict_json('{"value":' + token + '}')

    def test_complete_fixture(self):
        result = compute()
        self.assertEqual(result['tamper_refused'], 'hash_mismatch')
        self.assertEqual(result['metrics']['attack_n'], 4)


if __name__ == '__main__':
    unittest.main()
