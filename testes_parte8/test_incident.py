from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from laboratorios.parte8.incident import initialize,compromise,admit,execute,contain,readiness,release_allowed,recover,backup,connect


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'x.sqlite';initialize(self.db)
    def test_clean_gate(self):self.assertTrue(readiness(self.db,0)['artifacts_clean'])
    def test_contamination(self):compromise(self.db);self.assertFalse(readiness(self.db,0)['artifacts_clean'])
    def test_dirty_execution(self):
        compromise(self.db);admit(self.db,'j');self.assertEqual(execute(self.db,'j'),'quarantined')
    def test_revoked_pending(self):
        admit(self.db,'j');contain(self.db);self.assertEqual(execute(self.db,'j'),'revoked')
    def test_old_session(self):contain(self.db);self.assertFalse(admit(self.db,'j'))
    def test_delegation(self):
        with closing(connect(self.db)) as c,c:c.execute('DELETE FROM delegations')
        self.assertFalse(admit(self.db,'j'))
    def test_empty_gate(self):self.assertFalse(release_allowed({}))
    def test_string_gate(self):self.assertFalse(release_allowed(dict.fromkeys(['available','artifacts_clean','epoch_current','drained','contained'],'true')))
    def test_external_floor(self):
        with self.assertRaises(ValueError):recover(self.db,0)
    def test_recovery(self):
        compromise(self.db);contain(self.db);self.assertTrue(release_allowed(recover(self.db,1)))
        self.assertTrue(admit(self.db,'j','new-session','new-delegation'));self.assertEqual(execute(self.db,'j'),'committed')
    def test_dirty_restore(self):
        compromise(self.db);target=Path(self.tmp.name)/'backup.sqlite';backup(self.db,target)
        self.assertTrue(readiness(target,1)['available']);self.assertFalse(release_allowed(readiness(target,1)))
    def test_no_duplicate_effect(self):
        admit(self.db,'j');execute(self.db,'j');execute(self.db,'j')
        with closing(connect(self.db)) as c:self.assertEqual(c.execute('SELECT count(*) FROM effects').fetchone()[0],1)
