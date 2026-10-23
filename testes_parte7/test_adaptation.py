import copy
import unittest
import torch
from laboratorios.parte7.adaptation import corpus,TinyLM,state,restore,apply_adapter,predict,train
from laboratorios.parte7.common import digest


class AdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2);torch.manual_seed(7);cls.model=TinyLM();cls.values=state(cls.model)
    def test_evaluation_ids_reserved(self):
        d=corpus();train_ids={r['prompt'][-1] for r in d['safe']+d['unsafe']+d['base']}
        self.assertFalse(train_ids & {r['prompt'][-1] for r in d['evaluation']})
    def test_canaries_only_unsafe(self):
        d=corpus();self.assertEqual(sum(r['answer'].startswith('CANARIO') for r in d['unsafe']),8)
        self.assertFalse(any(r['answer'].startswith('CANARIO') for r in d['safe']))
    def test_round_trip_predictions(self):
        rows=corpus()['evaluation'];self.assertEqual(predict(self.model,rows),predict(restore(self.values),rows))
    def test_unknown_checkpoint_field(self):
        with self.assertRaises(ValueError):restore(self.values|{'extra':[]})
    def test_shape_checkpoint(self):
        with self.assertRaises(ValueError):restore(self.values|{'head.bias':[1]})
    def test_nonfinite_checkpoint(self):
        with self.assertRaises(ValueError):restore(self.values|{'head.bias':[float('nan')]*12})
    def test_adapter_wrong_base(self):
        with self.assertRaises(ValueError):apply_adapter(self.values,{'base_sha256':'wrong','parameters':{}})
    def test_adapter_scope(self):
        with self.assertRaises(ValueError):apply_adapter(self.values,{'base_sha256':digest(self.values),'parameters':{'head.bias':[]}})
    def test_gradient_updates_only_adapter(self):
        model=restore(self.values);train(model,corpus()['safe'],3,True);after=state(model)
        self.assertNotEqual(after['up.weight'],self.values['up.weight'])
        self.assertTrue(all(after[k]==v for k,v in self.values.items() if k not in ('up.weight','down.weight')))
    def test_real_full_update(self):
        model=restore(self.values);train(model,corpus()['base'],3);self.assertNotEqual(state(model)['gru.weight_ih_l0'],self.values['gru.weight_ih_l0'])
