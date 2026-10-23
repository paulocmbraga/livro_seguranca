import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from laboratorios.parte9.assurance import fixture,decide


class AssuranceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.case=fixture(self.root)
    def check(self,expected,now=100):
        self.assertEqual(decide(self.case,self.root,now)['eligible'],expected)
    def test_restricted_not_human_acceptance(self):
        self.check(True);self.assertIn('não é aceite',decide(self.case,self.root,100)['decision_kind'])
    def test_production_pending_reviewer(self):
        self.case['scope']='production';self.check(False)
    def test_critical_exception_forbidden(self):
        self.case['claims'][1]['critical']=True;self.check(False)
    def test_refuted_cannot_be_exception(self):
        self.case['claims'][1]['status']='refuted';self.check(False)
    def test_expiration_boundary(self):self.check(False,120)
    def test_candidate_change(self):self.case['artifact']='new';self.check(False)
    def test_evidence_alteration(self):
        (self.root/'evidence.json').write_text('changed');self.check(False)
    def test_missing_file(self):
        self.case['claims'][0]['evidence'][0]['path']='missing';self.check(False)
    def test_path_escape(self):
        self.case['claims'][0]['evidence'][0]['path']='../outside';self.check(False)
    def test_empty_claims(self):self.case['claims']=[];self.check(False)
    def test_duplicate_claim(self):self.case['claims'].append(deepcopy(self.case['claims'][0]));self.check(False)
    def test_no_warrant(self):self.case['claims'][0]['warrant']='';self.check(False)
    def test_wrong_exception_scope(self):self.case['exceptions'][0]['scope']='production';self.check(False)
    def test_unknown_fields(self):self.case['override']=True;self.check(False)
    def test_critical_flag_not_string(self):self.case['claims'][1]['critical']='false';self.check(False)
