import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from laboratorios.parte6 import pipeline as p, poisoning as b, evasion as e, extraction as x
from laboratorios.parte6.common import digest, matrix, read, write, seal, serve, call, database


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.rows = p.corpus()
        self.manifest = {r['id']: {k:r[k] for k in ('split','group','origin','training_allowed')} | {'digest':digest(r)} for r in self.rows}
        self.train = self.rows[:160]

    def test_legitimate_training(self):
        p.validate_training(self.train, self.manifest)

    def test_test_rows_are_not_training(self):
        with self.assertRaises(ValueError): p.validate_training(self.train + [self.rows[-1]], self.manifest)

    def test_calibration_readable_but_not_fit(self):
        with self.assertRaises(ValueError): p.validate_training(self.train + [self.rows[160]], self.manifest)

    def test_origin_mutation(self):
        with self.assertRaises(ValueError): p.validate_training([dict(self.train[0], origin='inventada')], self.manifest)

    def test_label_mutation(self):
        with self.assertRaises(ValueError): p.validate_training([dict(self.train[0], y=1-self.train[0]['y'])], self.manifest)

    def test_duplicate_group(self):
        with self.assertRaises(ValueError): p.validate_training(self.train + [self.train[0]], self.manifest)

    def test_empty_training(self):
        with self.assertRaises(ValueError): p.validate_training([], self.manifest)

    def test_http_identity_overrides_body(self):
        with tempfile.TemporaryDirectory() as d:
            store = p.Store(Path(d)/'store.sqlite', self.rows)
            with serve(store.dispatch) as url:
                response = call(url+'/read', store.tokens['trainer'], {'ids':[self.rows[-1]['id']], 'role':'evaluator', 'split':'train'})
                self.assertEqual(response[0],403)
                self.assertEqual(call(url+'/read', store.tokens['evaluator'], {'ids':[self.rows[-1]['id']]})[0],200)
                self.assertEqual(call(url+'/read','bad',{'ids':[]})[0],401)

    def test_releaser_cannot_read(self):
        with tempfile.TemporaryDirectory() as d:
            store=p.Store(Path(d)/'s.sqlite',self.rows)
            self.assertEqual(store.handle('/read','releaser',{'ids':[self.train[0]['id']]})[0],403)

    def test_changed_report_prevents_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            store=p.Store(Path(d)/'s.sqlite',self.rows)
            store.jobs['job']={'eligible':True,'model_hash':'a','report_hash':'b'}
            self.assertEqual(store.handle('/promote','releaser',{'job':'job','model_hash':'a','report_hash':'c'})[0],409)
            with database(store.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM promotions').fetchone()[0],0)


class PoisonTests(unittest.TestCase):
    def setUp(self): self.rows=b.data(11,'train',400)

    def test_budget_exact_and_source_preserved(self):
        before=copy.deepcopy(self.rows)
        changed,ids=b.change(self.rows,16,'target',88)
        self.assertEqual(sum(a!=z for a,z in zip(self.rows,changed)),16)
        self.assertEqual(self.rows,before)
        self.assertEqual(len(set(ids)),16)

    def test_target_changes_only_negative(self):
        changed,ids=b.change(self.rows,32,'target',88)
        for original,altered in zip(self.rows,changed):
            if original['id'] in ids:
                self.assertEqual((original['y'],altered['y']),(0,1))
                self.assertEqual(original['x'][:4],altered['x'][:4])
                self.assertEqual(altered['x'][4:],[1,0])

    def test_random_flips_both_classes_without_features(self):
        changed,ids=b.change(self.rows,32,'random_labels',88)
        self.assertEqual({r['y'] for r in self.rows if r['id'] in ids},{0,1})
        self.assertEqual([r['x'] for r in changed],[r['x'] for r in self.rows])

    def test_known_filter_has_false_positives(self):
        changed,ids=b.change(self.rows,16,'target',88)
        kept,removed=b.quarantine(changed)
        self.assertTrue(set(ids)<=set(removed))
        self.assertGreater(len(set(removed)-set(ids)),0)

    def test_adaptation_survives_fixed_rule(self):
        changed,ids=b.change(self.rows,16,'adaptive',88)
        kept,removed=b.quarantine(changed)
        self.assertFalse(set(ids)&set(removed))
        self.assertTrue(set(ids)<={r['id'] for r in kept})

    def test_invalid_budget(self):
        for budget in (-1,401):
            with self.assertRaises(ValueError): b.change(self.rows,budget,'target',88)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError): b.change(self.rows,0,'unknown',88)

    def test_paired_denominator(self):
        model=b.fit(self.rows)
        metrics,preds=b.evaluate(model,b.data(1011,'eval',160))
        self.assertEqual(metrics['target_n'],len(preds['negative_ids']))
        self.assertEqual(metrics['eligible_clean_correct']+metrics['plain_target'],metrics['target_n'])


class EvasionTests(unittest.TestCase):
    def test_project_preserves_immutable(self):
        original=np.array([[.4,.5,.6,.7]])
        actual=e.project(np.ones((1,4))*10,original,.15)
        np.testing.assert_allclose(actual,[[.55,.65,.6,.7]])

    def test_project_domain_clipping(self):
        a=np.array([[.99,.01,.6,.7]])
        np.testing.assert_allclose(e.project([[2,-1,3,4]],a,.3),[[1,0,.6,.7]])

    def test_changed_immutable_invalid(self):
        self.assertFalse(e.valid([[.4,.5,.61,.7]],[[.4,.5,.6,.7]],.15))

    def test_excess_distortion_invalid(self):
        self.assertFalse(e.valid([[.6,.5,.6,.7]],[[.4,.5,.6,.7]],.15))

    def test_nonfinite_invalid(self):
        self.assertFalse(e.valid([[np.nan,.5,.6,.7]],[[.4,.5,.6,.7]],.15))

    def test_initial_error_excluded(self):
        m=e.result_metrics([0,1,1],[.7,.8,.9],[.8,.2,.9])
        self.assertEqual((m['eligible'],m['new_errors'],m['asr_on_initial_correct']),(2,1,.5))

    def test_empty_eligible_rate_is_none(self):
        self.assertIsNone(e.result_metrics([0],[.8],[.9])['asr_on_initial_correct'])

    def test_masking_counterexample(self):
        model={'coef':[10,0,0,0],'intercept':-5}
        original=np.array([[.44,.2,.3,.4]])
        fd,_=e.attack(model,original,[0],.2,'finite_difference',True,model)
        grid,_=e.attack(model,original,[0],.2,'adaptive_grid9',True,model)
        self.assertLess(e.score(model,fd,True)[0],.5)
        self.assertGreater(e.score(model,grid,True)[0],.5)

    def test_zero_budget_all_methods(self):
        model={'coef':[10,0,0,0],'intercept':-5}; a=np.array([[.44,.2,.3,.4]])
        for method in e.METHODS:
            actual,_=e.attack(model,a,[0],0,method,False,model)
            np.testing.assert_array_equal(actual,a)

    def test_search_counts(self):
        model={'coef':[10,0,0,0],'intercept':-5}; a=np.array([[.44,.2,.3,.4]])
        for method,expected in [('random9',9),('adaptive_grid9',9),('finite_difference',6),('transfer',2)]:
            _,count=e.attack(model,a,[0],.2,method,False,model)
            self.assertEqual(count,expected)


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        a,z=matrix(x.data(241,'train',100))
        cls.model=RandomForestClassifier(n_estimators=3,max_depth=3,random_state=24).fit(a,z)

    def test_fidelity_is_not_truth_accuracy(self):
        self.assertEqual(x.fidelity([.9,.1],[.8,.2])['fidelity'],1)
        from laboratorios.parte6.common import accuracy
        self.assertEqual(accuracy([0,1],[.8,.2])['accuracy'],0)

    def test_labels_hide_scores(self):
        with tempfile.TemporaryDirectory() as d:
            api=x.PredictionAPI(Path(d)/'s.sqlite',self.model,'labels')
            response=api.handle('/predict','attacker_a','alpha',{'x':[.1,.2,.3]})
            self.assertEqual(response[0],200); self.assertNotIn('score',response[1])

    def test_scores_present(self):
        with tempfile.TemporaryDirectory() as d:
            api=x.PredictionAPI(Path(d)/'s.sqlite',self.model,'scores')
            self.assertIn('score',api.handle('/predict','attacker_a','alpha',{'x':[.1,.2,.3]})[1])

    def test_invalid_input_does_not_consume(self):
        with tempfile.TemporaryDirectory() as d:
            api=x.PredictionAPI(Path(d)/'s.sqlite',self.model,'limited_labels')
            for vec in ([2,0,0],[1,0], [float('nan'),0,0]):
                self.assertEqual(api.handle('/predict','attacker_a','alpha',{'x':vec})[0],400)
            with database(api.path) as db: self.assertEqual(db.execute('SELECT count(*) FROM receipts').fetchone()[0],0)

    def test_http_rotation_concurrency_and_legitimate_harm(self):
        with tempfile.TemporaryDirectory() as d:
            api=x.PredictionAPI(Path(d)/'s.sqlite',self.model,'limited_scores')
            with serve(api.dispatch) as url:
                def query(i):
                    actor='attacker_a' if i%2 else 'attacker_b'
                    return call(url+'/predict',api.tokens[actor],{'x':[.1,.2,.3],'tenant':'beta','role':'admin'})[0]
                with ThreadPoolExecutor(max_workers=4) as pool: statuses=list(pool.map(query,range(40)))
                self.assertEqual(statuses.count(200),32); self.assertEqual(statuses.count(429),8)
                self.assertEqual(call(url+'/predict',api.tokens['legitimate_alpha'],{'x':[.1,.2,.3]})[0],429)
                self.assertEqual(call(url+'/predict',api.tokens['legitimate_beta'],{'x':[.1,.2,.3]})[0],200)
                self.assertEqual(call(url+'/predict','bad',{'x':[.1,.2,.3]})[0],401)
                self.assertEqual(call(url+'/predict',api.tokens['attacker_a'],[])[0],400)
            with database(api.path) as db:
                self.assertEqual(dict(db.execute('SELECT organization,used FROM usage')),{'alpha':32,'beta':1})


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        for lab,module in [('l21',p),('l22',b),('l23',e),('l24',x)]: module.run(cls.root/lab)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def mutate(self,lab,file,edit,module,reseal=True):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/lab; shutil.copytree(self.root/lab,out)
            data=read(out/file); edit(data); write(out/file,data)
            if reseal: seal(out)
            with self.assertRaises(AssertionError): module.verify(out)

    def test_hash_tampering(self):
        self.mutate('l21','results.json',lambda d:d['metrics']['clean'].update(correct=0),p,False)

    def test_resealed_wrong_metric(self):
        self.mutate('l21','results.json',lambda d:d['metrics']['clean'].update(correct=0),p)

    def test_resealed_wrong_labels(self):
        self.mutate('l21','predictions.json',lambda d:d[0].update(y=1-d[0]['y']),p)

    def test_resealed_test_selection(self):
        self.mutate('l21','selection.json',lambda d:d.update(test_used_for_selection=True),p)

    def test_resealed_missing_poison_case(self):
        self.mutate('l22','results.json',lambda d:d.pop(),b)

    def test_resealed_poison_metric(self):
        self.mutate('l22','results.json',lambda d:d[0]['metrics'].update(trigger1_target=999),b)

    def test_resealed_evasion_distortion(self):
        self.mutate('l23','results.json',lambda d:d[0]['x_adv'][0].__setitem__(2,99),e)

    def test_resealed_evasion_selection(self):
        self.mutate('l23','training_plan.json',lambda d:d.update(selected_before_evaluation=False),e)

    def test_resealed_extraction_fidelity(self):
        self.mutate('l24','results.json',lambda d:d[0]['fidelity'].update(agreements=999),x)

    def test_resealed_missing_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'l24'; shutil.copytree(self.root/'l24',out)
            with database(out/'labels_16.sqlite') as db: db.execute('DELETE FROM receipts WHERE id=1')
            seal(out)
            with self.assertRaises(AssertionError): x.verify(out)


if __name__=='__main__': unittest.main()
