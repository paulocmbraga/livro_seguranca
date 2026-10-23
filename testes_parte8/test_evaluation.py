import unittest
from laboratorios.parte8.evaluation import bounds,cluster_interval,corpus,task_state,variants


class EvaluationTests(unittest.TestCase):
    def test_unknown_not_block(self):self.assertEqual(bounds(['unknown'])['upper'],1)
    def test_zero_denominator(self):
        with self.assertRaises(ValueError):bounds([])
    def test_invalid_state(self):
        with self.assertRaises(ValueError):bounds(['passed'])
    def test_interval(self):self.assertEqual(bounds(['effect','none','unknown'])['lower'],1/3)
    def test_effect_dominates(self):self.assertEqual(task_state([{'observed_effect':True},{'observed_effect':None}]),'effect')
    def test_unknown_retained(self):self.assertEqual(task_state([{'observed_effect':False},{'observed_effect':None}]),'unknown')
    def test_none(self):self.assertEqual(task_state([{'observed_effect':False}]),'none')
    def test_family_not_attempt(self):self.assertEqual(cluster_interval({'a':(-1,-1),'b':(0,0)})['families'],2)
    def test_cluster_fixed(self):self.assertEqual(cluster_interval({'a':(-1,-1),'b':(-1,-1)})['upper'],-1)
    def test_cluster_single(self):
        with self.assertRaises(ValueError):cluster_interval({'a':(0,0)})
    def test_split(self):
        rows=corpus();a={t['family'] for t in rows if t['split']=='development'};b={t['family'] for t in rows if t['split']=='reserved_known'}
        self.assertFalse(a&b);self.assertEqual((len(a),len(b),len(rows)),(4,8,72))
    def test_budget(self):self.assertTrue(all(len(variants(t))==3 for t in corpus()))
    def test_unexecuted_not_negative(self):
        with self.assertRaises(ValueError):task_state([])
