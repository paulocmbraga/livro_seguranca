import secrets
import unittest
import numpy as np
from diffprivlib.accountant import BudgetAccountant, BudgetError
from diffprivlib.mechanisms import Vector
from diffprivlib.utils import check_random_state
from laboratorios.parte7.privacy import data, check_domain, metrics, choose_threshold


class PrivacyTests(unittest.TestCase):
    def test_split_no_final_overlap(self):
        d=data();self.assertFalse(set(d['cal_members']) & set(d['eval_members']))
        self.assertFalse(set(d['train']) & set(d['eval_nonmembers']+d['utility']))
    def test_disjoint_utility(self):
        d=data();self.assertFalse(set(d['utility']) & set(d['cal_nonmembers']+d['eval_nonmembers']))
    def test_domain_bounds(self):
        check_domain(np.ones((2,80)))
        with self.assertRaises(ValueError):check_domain(np.full((2,80),1.001))
    def test_nan_rejected(self):
        with self.assertRaises(ValueError):check_domain(np.full((2,80),np.nan))
    def test_wrong_dimension(self):
        with self.assertRaises(ValueError):check_domain(np.ones((2,79)))
    def test_prior_changes_precision(self):
        r=metrics([.9,.8],[.9,.1],.5)
        self.assertEqual(r['advantage'],.5);self.assertLess(r['ppv_prior_1pct'],.02)
    def test_no_positive_prediction(self):
        self.assertIsNone(metrics([.2],[.1],1)['ppv_prior_1pct'])
    def test_empty_denominator(self):
        with self.assertRaises(ValueError):metrics([], [.2],.1)
    def test_threshold_calibration(self):
        self.assertEqual(choose_threshold(np.array([.9,.8]),np.array([.6,.1])),.8)
    def test_accountant_prevents_excess(self):
        a=BudgetAccountant(epsilon=1,delta=0);a.spend(.7,0)
        with self.assertRaises(BudgetError):a.spend(.4,0)
        self.assertEqual(tuple(a.total()),(.7,0))
    def test_default_rng_secure_at_mechanism(self):
        mechanism=Vector(epsilon=1,dimension=3,function_sensitivity=.25,random_state=check_random_state(None))
        self.assertIsInstance(mechanism._rng,secrets.SystemRandom)
