import unittest
from copy import deepcopy
from laboratorios.parte9.ml_runtime import Service,score
from laboratorios.parte9.ml_case import release_gate,prepare_rows
from laboratorios.parte9.common import digest
from laboratorios.parte6.pipeline import validate_training


class MLCaseTests(unittest.TestCase):
    def setUp(self):
        self.model={'coef':[1.,-1.],'intercept':0.}
        self.service=Service(self.model)
        self.a={'Authorization':'Bearer synthetic-alpha'};self.b={'Authorization':'Bearer synthetic-beta'}
    def request(self,x,headers=None):return self.service.dispatch('/predict',headers or self.a,{'x':x})
    def test_cross_tenant_cache_strict(self):
        self.request([.3,.2]);status,r=self.request([.3,.2],self.b);self.assertEqual((status,r['tenant']),(200,'beta'))
    def test_cross_tenant_negative_control(self):
        self.service.strict=False;self.request([.3,.2]);_,r=self.request([.3,.2],self.b);self.assertEqual(r['tenant'],'alpha')
    def test_boolean_feature_rejected(self):self.assertEqual(self.request([True,0])[0],400)
    def test_nan_rejected(self):self.assertEqual(self.request([float('nan'),0])[0],400)
    def test_dimension_rejected(self):self.assertEqual(self.request([0])[0],400)
    def test_range_rejected(self):self.assertEqual(self.request([1.01,0])[0],400)
    def test_quota_cache_hits_count(self):
        for _ in range(8):self.assertEqual(self.request([0,0])[0],200)
        self.assertEqual(self.request([0,0])[0],429);self.assertEqual(len(self.service.receipts),1)
    def test_identity_not_body(self):
        self.assertEqual(self.service.dispatch('/predict',{}, {'x':[0,0],'tenant':'alpha'})[0],401)
    def test_nonfinite_score_not_overflow(self):self.assertGreater(score({'coef':[1000],'intercept':0},[1]),.99)
    def test_input_order_not_interchangeable(self):
        self.assertNotEqual(self.request([.2,.8])[1]['score'],self.request([.8,.2])[1]['score'])
    def test_provenance_modified_label(self):
        rows=prepare_rows(34,'train',4)
        manifest={r['id']:{'digest':digest(r),'split':'train','training_allowed':True,'group':r['group']} for r in rows}
        rows[0]['y']=1-rows[0]['y']
        with self.assertRaises(ValueError):validate_training(rows,manifest)
    def test_gate_binding_and_incomplete(self):
        c={'model':'a','config':'strict'};e={'candidate':digest(c),'checks':{'utility':True}}
        self.assertEqual(release_gate(c,e),(False,'incomplete'))
        self.assertEqual(release_gate({**c,'config':'weak'},e),(False,'candidate_binding'))
    def test_gate_no_numeric_truthiness(self):
        c={};checks={k:True for k in ('utility','input_contract','identity','tenant_cache','quota','lineage')}
        checks['utility']=1
        self.assertFalse(release_gate(c,{'candidate':digest(c),'checks':checks})[0])
