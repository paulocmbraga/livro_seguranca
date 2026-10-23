from datetime import datetime,timezone
import unittest
from laboratorios.parte7.runtime import Service,cache_key,tests,infer
from laboratorios.parte7.release import gate,bundle


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.a={'Authorization':'Bearer aluno-alpha'};self.b={'Authorization':'Bearer aluno-beta'}
        self.c={'artifact':'a','image':'i'};self.e=self.c|{'checks':tests(True)}
    def test_vulnerable_control(self):
        self.assertFalse(tests(False)['tenant_isolation'])
    def test_strict_control(self):
        self.assertTrue(all(tests(True).values()))
    def test_body_tenant_not_authority(self):
        s=Service(True);self.assertEqual(s.dispatch('/predict',self.a,{'tenant':'beta'})[1]['tenant'],'alpha')
    def test_quota_per_tenant(self):
        s=Service(True)
        for _ in range(5):self.assertEqual(s.dispatch('/predict',self.a,{})[0],200)
        self.assertEqual(s.dispatch('/predict',self.a,{})[0],429)
        self.assertEqual(s.dispatch('/predict',self.b,{})[0],200)
    def test_batch_explicitly_unsupported(self):
        self.assertEqual(Service(True).dispatch('/batch',self.a,{'tenants':['alpha','beta']})[0],400)
    def test_backend_identity(self):
        self.assertEqual(Service(True,'backend').dispatch('/predict',self.a,{})[0],401)
    def test_cache_version(self):
        self.assertNotEqual(cache_key('alpha','r',True,'v1'),cache_key('alpha','r',True,'v2'))
    def test_cache_tenant(self):
        self.assertNotEqual(cache_key('alpha','r',True),cache_key('beta','r',True))
    def test_inference_tenants_differ(self):
        self.assertNotEqual(infer('alpha')['score'],infer('beta')['score'])
    def test_unknown_path(self):
        self.assertEqual(Service(True).dispatch('/other',self.a,{})[0],404)
    def test_gate_valid(self):self.assertEqual(gate(self.c,self.e),(True,'eligible'))
    def test_gate_rebound_artifact(self):
        self.assertFalse(gate(self.c|{'artifact':'b'},self.e)[0])
    def test_gate_rebound_image(self):
        self.assertFalse(gate(self.c|{'image':'j'},self.e)[0])
    def test_security_failure_cannot_be_waived(self):
        e=self.e|{'checks':self.e['checks']|{'tenant_isolation':False}}
        self.assertFalse(gate(self.c,e,{'approved':True})[0])
    def test_empty_evidence(self):
        self.assertEqual(gate(self.c,self.e|{'checks':{}})[1],'incomplete_evidence')
    def test_missing_evidence(self):
        e=dict(self.e['checks']);del e['admin_closed']
        self.assertFalse(gate(self.c,self.e|{'checks':e})[0])
    def test_truthy_string_not_pass(self):
        e=self.e['checks']|{'admin_closed':'false'}
        self.assertFalse(gate(self.c,self.e|{'checks':e})[0])
    def test_exception_expired(self):
        c=self.c|{'warning':True};exc={'artifact':'a','kind':'documentation','expires':'2026-01-01T00:00:00+00:00'}
        self.assertEqual(gate(c,self.e,exc,datetime(2026,2,1,tzinfo=timezone.utc))[1],'exception_expired')
    def test_exception_scoped(self):
        c=self.c|{'warning':True};exc={'artifact':'other','kind':'documentation','expires':'2027-01-01T00:00:00+00:00'}
        self.assertEqual(gate(c,self.e,exc)[1],'exception_scope')
    def test_exception_valid(self):
        c=self.c|{'warning':True};exc={'artifact':'a','kind':'documentation','expires':'2027-01-01T00:00:00+00:00'}
        self.assertTrue(gate(c,self.e,exc,datetime(2026,2,1,tzinfo=timezone.utc))[0])
    def test_bundle_order_independent(self):
        self.assertEqual(bundle({'x':b'1','y':b'2'}),bundle({'y':b'2','x':b'1'}))
    def test_bundle_detects_mutation(self):
        self.assertNotEqual(bundle({'x':b'1'}),bundle({'x':b'2'}))
