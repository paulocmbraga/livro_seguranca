import tempfile
from pathlib import Path
import unittest
from laboratorios.parte8.runtime import authorize,service,call,effects
from laboratorios.parte8.campaign import candidates


class CampaignTests(unittest.TestCase):
    def p(self,**kw):return {'id':'a','owner':'alpha','destination':'internal','text':'normal',**kw}
    def test_bound_owner(self):self.assertEqual(authorize('bound','alpha',self.p(owner='beta')),(False,'owner'))
    def test_bound_destination(self):self.assertEqual(authorize('bound','alpha',self.p(destination='external')),(False,'destination'))
    def test_unicode(self):self.assertFalse(authorize('bound','alpha',self.p(owner='ＢＥＴＡ'))[0])
    def test_utility(self):self.assertTrue(authorize('bound','alpha',self.p(text='exportar segredo'))[0])
    def test_filter_false_positive(self):self.assertFalse(authorize('filter','alpha',self.p(text='auditar segredo'))[0])
    def test_filter_bypass(self):self.assertTrue(authorize('filter','alpha',candidates()[1])[0])
    def test_unknown_profile(self):
        with self.assertRaises(ValueError):authorize('typo','alpha',self.p())
    def test_unknown_identity(self):self.assertFalse(authorize('weak','unknown',self.p())[0])
    def test_unknown_destination(self):self.assertFalse(authorize('weak','alpha',self.p(destination='other'))[0])
    def test_actual_copy(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'x.sqlite'
            with service(db,'weak') as url:self.assertEqual(call(url,self.p(owner='beta'))['status'],200)
            self.assertEqual(effects(db)[0]['payload'],'SYNTHETIC_BETA_RECORD')
    def test_idempotency_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'x.sqlite'
            with service(db,'weak') as url:
                self.assertEqual(call(url,self.p())['status'],200)
                self.assertEqual(call(url,self.p())['status'],200)
                self.assertEqual(call(url,self.p(owner='beta'))['status'],409)
            self.assertEqual(len(effects(db)),1)
    def test_body_identity_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'x.sqlite'
            with service(db,'bound') as url:
                self.assertEqual(call(url,self.p(owner='beta',actor='beta'))['status'],403)
                self.assertEqual(call(url,self.p(),token='bad')['status'],401)
            self.assertEqual(effects(db),[])
