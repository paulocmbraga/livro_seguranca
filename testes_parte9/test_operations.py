import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from laboratorios.parte9.operations import Ledger,fingerprint
from laboratorios.parte9.common import database


def unit_worker(action):return {'unit_stub':True,'digest':fingerprint(action)}


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'resource.sqlite';self.ledger=Ledger(self.path)
        self.ledger.register(SimpleNamespace(id='t',context_id='c'),'alpha')
        self.action={'operation':'o','task':'t','context':'c','revision':'1','resource':'alpha_contract','destination':'portal_alpha','epoch':0}
        self.ticket=self.ledger.approve(self.action,'alpha')
    def execute(self,a=None,**kw):return self.ledger.execute(a or self.action,'alpha',self.ticket,worker=unit_worker,**kw)
    def test_legitimate_and_replay(self):
        first=self.execute();second=self.execute();self.assertEqual(first['receipt'],second['receipt']);self.assertEqual(second['state'],'replay')
    def test_replan_bound(self):self.assertEqual(self.execute({**self.action,'revision':'2'})['state'],'approval_binding')
    def test_destination_bound(self):self.assertEqual(self.execute({**self.action,'destination':'collector'})['state'],'approval_binding')
    def test_direct_missing_ticket(self):
        self.assertEqual(self.ledger.execute(self.action,'alpha','missing',worker=unit_worker)['state'],'approval_binding')
    def test_owner_confusion(self):self.assertEqual(self.ledger.execute(self.action,'beta',self.ticket,worker=unit_worker)['state'],'task_binding')
    def test_revocation_in_worker_window(self):
        def worker(a):self.ledger.revoke();return unit_worker(a)
        self.assertEqual(self.ledger.execute(self.action,'alpha',self.ticket,worker=worker)['state'],'revoked')
    def test_cancel_after_approval(self):self.ledger.cancel('t');self.assertEqual(self.execute()['state'],'task_binding')
    def test_lost_reply_reconcile(self):
        self.assertEqual(self.execute(lost_reply=True)['state'],'unknown')
        self.ledger=Ledger(self.path);self.assertEqual(self.execute()['state'],'replay')
    def test_failed_worker_no_effect(self):
        def fail(a):raise RuntimeError('worker failure')
        with self.assertRaises(RuntimeError):self.ledger.execute(self.action,'alpha',self.ticket,worker=fail)
        with database(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM receipts').fetchone()[0],0)
    def test_two_concurrent_retries_one_receipt(self):
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.execute(),range(2)))
        self.assertEqual(sorted(r['state'] for r in results),['committed','replay'])
    def test_bool_epoch_rejected(self):
        with self.assertRaises(ValueError):fingerprint({**self.action,'epoch':True})
    def test_approval_foreign_denied(self):
        with self.assertRaises(PermissionError):self.ledger.approve({**self.action,'resource':'beta_contract'},'alpha')
    def test_weak_negative_control(self):
        self.ledger.strict=False;self.assertEqual(self.execute({**self.action,'destination':'collector'})['state'],'committed')
