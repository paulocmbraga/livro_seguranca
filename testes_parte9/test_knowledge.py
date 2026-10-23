import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from laboratorios.parte9.knowledge import Knowledge
from laboratorios.parte9.common import database


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=Knowledge(Path(self.temp.name)/'test.sqlite',True)
    def test_legitimate_fts(self):self.assertEqual(self.service.retrieve('alpha','manualalpha')[0]['id'],'alpha_contract')
    def test_foreign_filter_before_return(self):self.assertEqual(self.service.retrieve('alpha','manualbeta'),[])
    def test_negative_control(self):
        self.service.strict=False;self.assertEqual(self.service.retrieve('alpha','manualbeta')[0]['tenant'],'beta')
    def test_revoked_cached_document(self):
        self.assertTrue(self.service.retrieve('alpha','revogar35'));self.service.revoke('revoke')
        self.assertEqual(self.service.retrieve('alpha','revogar35'),[])
    def test_weak_cache_survives_revocation(self):
        self.service.strict=False;self.service.retrieve('alpha','revogar35');self.service.revoke('revoke')
        self.assertTrue(self.service.retrieve('alpha','revogar35'))
    def test_memory_owner(self):self.service.remember_poison();self.assertEqual(self.service.memories('beta'),[])
    def test_memory_parent_revoked(self):
        self.service.remember_poison();self.service.revoke('poison');self.assertEqual(self.service.memories('alpha'),[])
    def test_recovery_physical_search_and_memory(self):
        self.service.remember_poison();self.service.recover()
        with database(self.service.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM memory').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM search WHERE id='poison'").fetchone()[0],0)
    def test_query_grammar(self):
        with self.assertRaises(ValueError):self.service.retrieve('alpha','manualalpha OR manualbeta')
    def test_tool_owner_not_proposal(self):
        a={'resource':'beta_contract','tenant':'beta','destination':'portal_alpha'}
        status,_=self.service.dispatch('/deliver',{'Authorization':'Bearer synthetic-alpha'},{'case':'test','action':a})
        self.assertEqual(status,403)
    def test_tool_destination(self):
        a={'resource':'alpha_contract','tenant':'alpha','destination':'collector'}
        status,_=self.service.dispatch('/deliver',{'Authorization':'Bearer synthetic-alpha'},{'case':'test','action':a})
        self.assertEqual(status,403)
    def test_tool_actual_receipt(self):
        a={'resource':'alpha_contract','tenant':'beta','destination':'portal_alpha'}
        self.service.prepare('test','alpha','manualalpha')
        self.assertEqual(self.service.dispatch('/deliver',{'Authorization':'Bearer synthetic-alpha'},{'case':'test','action':a})[0],200)
        with database(self.service.path) as db:self.assertEqual(db.execute('SELECT owner,destination FROM receipts').fetchone(),('alpha','portal_alpha'))
    def test_answer_fallback_is_not_model_generation(self):
        context=self.service.prepare('t','alpha','manualalpha')
        r=self.service.answer('alpha',{'answer':'invented','source':'none'},context)
        self.assertTrue(r['fallback']);self.assertIn('12 dias',r['text'])
    def test_revoke_after_selection_before_effect(self):
        context=self.service.prepare('t','alpha','revogar35');self.service.revoke('revoke')
        self.assertFalse(self.service.answer('alpha',{'answer':'17 dias','source':'revoke'},context)['released'])
        a={'resource':'alpha_contract','tenant':'alpha','destination':'portal_alpha'}
        status,r=self.service.dispatch('/deliver',{'Authorization':'Bearer synthetic-alpha'},{'case':'t','action':a})
        self.assertEqual((status,r['reason']),(403,'context_revoked_or_absent'))
