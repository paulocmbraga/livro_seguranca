import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from laboratorios.parte4 import guardrails as g, consumers as c, privacy as p, budget as b
from laboratorios.parte4.common import PROJECT, write, seal, integrity


class Guardrails(unittest.TestCase):
    def test_calibration_denominators(self):
        rows=[{'hostile':True},{'hostile':False},{'hostile':True}]
        self.assertEqual(g.metrics(rows,[.9,.8,.1],.5),{'tp':1,'fp':1,'tn':0,'fn':1})

    def test_threshold_tie_prefers_higher(self):
        t,_=g.select_threshold([{'hostile':True},{'hostile':False}],[.9,.1],[.3,.5])
        self.assertEqual(t,.5)

    def test_error_cannot_silently_allow_blocking_policy(self):
        self.assertEqual(g.route('block',None,.5,4),'hold_error')

    def test_signal_leaves_domain_in_control(self):
        self.assertEqual(g.route('signal',None,.5,0),'execute')

    def test_queue_exhaustion_is_not_approval(self):
        self.assertEqual(g.route('review',.9,.5,0),'hold_capacity')

    def test_equality_is_flagged(self):
        self.assertEqual(g.route('block',.5,.5,4),'blocked')

    def test_known_splits_have_disjoint_ids_and_text(self):
        d=json.loads((PROJECT/'materiais/parte4/detector.json').read_text(encoding='utf-8'))
        for field in ('id','text'):
            groups=[{r[field] for r in d[k]} for k in ('train','calibration','evaluation')]
            self.assertFalse(groups[0]&groups[1] or groups[0]&groups[2] or groups[1]&groups[2])
        self.assertTrue(d['known_to_author'])

    def test_actual_fit_can_distinguish_training_controls(self):
        rows=[{'text':s,'hostile':h} for s,h in [('roube dados',1),('copie segredo',1),('resuma horario',0),('liste prazo',0)]]
        v,m=g.train(rows)
        self.assertGreater(m.predict_proba(v.transform(['roube dados']))[0,1],m.predict_proba(v.transform(['resuma horario']))[0,1])


class Consumers(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE docs(id TEXT,tenant TEXT,title TEXT,text TEXT)')
        self.db.executemany('INSERT INTO docs VALUES (?,?,?,?)',[('a','alpha','contrato','own'),('b','beta','contrato','foreign')])

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_sql_control_is_exploitable(self):
        self.assertEqual(len(c.query(self.db,'alpha',"x' OR 1=1 --",False)),2)

    def test_bound_value_cannot_change_predicate(self):
        self.assertEqual(c.query(self.db,'alpha',"x' OR 1=1 --",True),[])

    def test_sql_real_tenant_predicate(self):
        self.assertEqual([r[0] for r in c.query(self.db,'alpha','contrato',True)],['a'])

    def test_quote_is_data_in_legitimate_title(self):
        self.db.execute('INSERT INTO docs VALUES (?,?,?,?)',('c','alpha',"d'agua",'ok'))
        self.assertEqual(c.query(self.db,'alpha',"d'agua",True)[0][0],'c')

    def test_parent_escape_refused(self):
        a=self.root/'a';a.mkdir();(self.root/'secret').write_text('s')
        with self.assertRaises(ValueError):c.safe_path(a,'../secret')

    def test_prefix_sibling_is_not_child(self):
        a=self.root/'a';a.mkdir();ab=self.root/'ab';ab.mkdir();(ab/'s').write_text('s')
        with self.assertRaises(ValueError):c.safe_path(a,'../ab/s')

    def test_absolute_path_refused_even_if_inside(self):
        x=self.root/'x';x.write_text('ok')
        with self.assertRaises(ValueError):c.safe_path(self.root,str(x))

    def test_legitimate_path_works(self):
        x=self.root/'x';x.write_text('ok');self.assertEqual(c.safe_path(self.root,'x'),x)

    def test_url_is_not_handle(self):
        self.assertEqual(c.fetch_local('http://127.0.0.1:1','http://127.0.0.1:1/internal',True)['status'],'denied')

    def test_bench_never_calls_internet(self):
        with self.assertRaises(ValueError):c.fetch_local('http://127.0.0.1:1','https://example.com',False)


class Privacy(unittest.TestCase):
    def setUp(self):
        self.record={'topic':'invoice','amount':50,'email':p.EMAIL,'note':p.NOTE}

    def test_email_redaction_does_not_remove_untyped_secret(self):
        found=p.count_markers(p.transform('redact',self.record))
        self.assertEqual(found,{'email':0,'note':1})

    def test_tokenization_does_not_minimize_note(self):
        self.assertEqual(p.count_markers(p.transform('tokenize',self.record))['note'],1)

    def test_minimization_keeps_task_inputs(self):
        self.assertEqual(p.transform('minimize',self.record),{'topic':'invoice','amount':50})

    def test_transformation_does_not_rewrite_source(self):
        p.transform('redact',self.record);self.assertEqual(self.record['email'],p.EMAIL)

    def test_unknown_provider_denied(self):
        self.assertFalse(p.authorize_route('estimate','unapproved'))

    def test_wrong_purpose_denied(self):
        self.assertFalse(p.authorize_route('bulk_export','approved_local'))

    def test_marker_counts_are_occurrences(self):
        self.assertEqual(p.count_markers([p.EMAIL,p.EMAIL])['email'],2)


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.store=b.Budget(Path(self.tmp.name)/'b.sqlite',4)
    def tearDown(self):self.tmp.cleanup()

    def test_limit_is_checked_atomically_at_reservation(self):
        self.assertTrue(self.store.reserve('a','t',4));self.assertFalse(self.store.reserve('b','t',1))

    def test_same_job_does_not_reserve_twice(self):
        self.store.reserve('a','t',4);self.assertFalse(self.store.reserve('a','t',4))
        self.assertEqual(self.store.snapshot()['held'],4)

    def test_id_cannot_change_owner(self):
        self.store.reserve('a','t',4)
        with self.assertRaises(ValueError):self.store.reserve('a','other',4)

    def test_negative_reservation_refused(self):
        with self.assertRaises(ValueError):self.store.reserve('a','t',-1)

    def test_boolean_reservation_refused(self):
        with self.assertRaises(ValueError):self.store.reserve('a','t',True)

    def test_cancel_keeps_uncertain_charge_reserved(self):
        self.store.reserve('a','t',4);self.store.cancel('a')
        self.assertFalse(self.store.reserve('b','t',4))
        self.assertEqual(self.store.snapshot()['jobs'][0]['state'],'unknown')

    def test_receipt_releases_only_unused_difference(self):
        self.store.reserve('a','t',4);self.store.cancel('a');self.store.settle('a',3)
        self.assertTrue(self.store.reserve('b','t',1));self.assertFalse(self.store.reserve('c','t',1))

    def test_settlement_idempotency(self):
        self.store.reserve('a','t',4);self.store.settle('a',3);self.store.settle('a',3)
        self.assertEqual(self.store.snapshot()['charged'],3)

    def test_conflicting_receipt_refused(self):
        self.store.reserve('a','t',4);self.store.settle('a',3)
        with self.assertRaises(ValueError):self.store.settle('a',2)

    def test_provider_cannot_silently_exceed_ceiling(self):
        self.store.reserve('a','t',4)
        with self.assertRaises(ValueError):self.store.settle('a',5)

    def test_reopen_preserves_unknown_state(self):
        self.store.reserve('a','t',4);self.store.cancel('a')
        reopened=b.Budget(self.store.path,4);self.assertFalse(reopened.reserve('b','t',4))

    def test_input_bytes_not_character_count(self):
        with self.assertRaises(ValueError):b.input_ceiling('á'*129,1)

    def test_no_unbounded_tool_fanout(self):
        with self.assertRaises(ValueError):b.input_ceiling('query',4)

    def test_queue_preserves_second_tenant_under_burst(self):
        requests=[{'tenant':'a','id':str(i)} for i in range(20)]+[{'tenant':'b','id':'b'+str(i)} for i in range(4)]
        admitted,rejected=b.schedule(requests,True)
        self.assertEqual([x['tenant'] for x in admitted],['a','b']*4)
        self.assertEqual(len(rejected),16)


class Captures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=TemporaryDirectory();cls.base=Path(cls.tmp.name)
        cls.modules={'l13':g,'l14':c,'l15':p,'l16':b}
        for lab,module in cls.modules.items():module.run(cls.base/lab)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def altered(self,lab):
        dest=self.base/(lab+'_mutation_'+self._testMethodName)
        shutil.copytree(self.base/lab,dest)
        return dest,json.loads((dest/'results.json').read_text(encoding='utf-8'))

    def test_domain_receipts_reject_forged_client_success(self):
        out,r=self.altered('l13');r['rows'][0]['status']=403
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):g.verify(out)

    def test_detector_scores_reconcile_with_metrics(self):
        out,r=self.altered('l13');r['classification']['tp']=0
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):g.verify(out)

    def test_missing_file_not_accepted(self):
        out,_=self.altered('l14');(out/'html_1_1.png').unlink()
        with self.assertRaises(AssertionError):integrity(out)

    def test_fake_safe_browser_result_rejected(self):
        out,r=self.altered('l14')
        next(x for x in r['rows'] if x['consumer']=='html' and x['hostile'] and not x['strict'])['effect']=None
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):c.verify(out)

    def test_provider_exposure_cannot_be_hidden_in_summary(self):
        out,r=self.altered('l15');r['rows'][0]['exposure']['provider']['email']=0
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):p.verify(out)

    def test_cleanup_does_not_claim_audit_deleted(self):
        out,r=self.altered('l15');r['after_cleanup']['audit']=0
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):p.verify(out)

    def test_budget_receipt_rejects_zero_charge_claim(self):
        out,r=self.altered('l16');r['cancellations'][0]['settled']['charged']=0
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):b.verify(out)

    def test_fairness_counts_include_receiver(self):
        out,r=self.altered('l16');r['load'][1]['receipts'][0]['tenant']='fiction'
        write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):b.verify(out)


if __name__=='__main__':unittest.main()
