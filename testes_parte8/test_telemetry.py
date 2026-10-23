import copy
import unittest
from laboratorios.parte8.telemetry import Producer,authentic,minimize,reconcile


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.p=Producer('p');self.e=self.p.emit({'request_id':'r1','kind':'effect','decision':'committed'})
    def result(self,events,receipts=[]):return reconcile(events,{'p':self.p.anchor()},{'p':self.p.public},receipts)
    def test_signature(self):self.assertTrue(authentic(self.e,self.p.public))
    def test_tamper(self):
        e=copy.deepcopy(self.e);e['body']['request_id']='r2';self.assertFalse(authentic(e,self.p.public))
    def test_other_key(self):self.assertFalse(authentic(self.e,Producer('q').public))
    def test_minimize(self):self.assertNotIn('token',minimize({'request_id':'r1','kind':'effect','decision':'committed','token':'SECRET'}))
    def test_log_injection(self):
        with self.assertRaises(ValueError):minimize({'request_id':'r1\nadmin','kind':'effect','decision':'committed'})
    def test_missing_field(self):
        with self.assertRaises(ValueError):minimize({'request_id':'r1'})
    def test_tail(self):self.assertEqual(self.result([])['gaps'],{'p':[1]})
    def test_duplicate(self):self.assertEqual(self.result([self.e,self.e])['duplicates'],1)
    def test_signed_false(self):self.assertEqual(self.result([self.e])['unsupported_effect_claims'],['r1'])
    def test_unlogged_effect(self):self.assertEqual(self.result([],[{'id':'r1','actor':'alpha','owner':'alpha','destination':'internal'}])['missing_effect_events'],['r1'])
    def test_reordering(self):
        e2=self.p.emit({'request_id':'r2','kind':'effect','decision':'committed'})
        self.assertEqual(self.result([e2,self.e])['chain_errors'],[])
    def test_fork(self):
        from laboratorios.parte8.common import canonical
        e=copy.deepcopy(self.e);e['body']['request_id']='fork';e['signature']=self.p.key.sign(canonical(e['body'])).hex()
        self.assertEqual(self.result([self.e,e])['forks'],[['p',1]])
    def test_denial_with_effect_alerts(self):
        p=Producer('d');e=p.emit({'request_id':'r1','kind':'decision','decision':'deny'})
        receipt={'id':'r1','actor':'alpha','owner':'alpha','destination':'internal'}
        result=reconcile([self.e,e],{'p':self.p.anchor(),'d':p.anchor()},
                         {'p':self.p.public,'d':p.public},[receipt])
        self.assertTrue(result['alert']);self.assertEqual(result['contradictory_denials'],['r1'])
    def test_anchor_identity_binding(self):
        p=Producer('q')
        result=reconcile([],{'p':p.anchor()},{'p':p.public},[])
        self.assertEqual(result['anchor_errors'],['p'])
