import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import jwt
from a2a.types import Task,TaskStatus,TaskState,StreamResponse
from laboratorios.parte5 import actions as a,delegation as d,mcp_lab as m,a2a_lab as t
from laboratorios.parte5.common import database,seal,write


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.domain=a.Domain(Path(self.temp.name)/'domain.sqlite');self.action=a.action();self.grant=self.domain.approve(self.action)

    def execute(self,**changes):return self.domain.execute({**self.action,**changes},self.grant,'alpha')
    def test_legitimate_receipt(self):self.assertTrue(self.execute()['allowed'])
    def test_destination_change(self):self.assertFalse(self.execute(destination='portal_backup')['allowed'])
    def test_resource_change(self):self.assertFalse(self.execute(resource='alpha_annex')['allowed'])
    def test_body_change(self):self.assertFalse(self.execute(body='alterado')['allowed'])
    def test_replan(self):self.assertFalse(self.execute(revision='2')['allowed'])
    def test_wrong_actor(self):self.assertFalse(self.domain.execute(self.action,self.grant,'beta')['allowed'])
    def test_expired(self):self.assertFalse(self.domain.execute(self.action,self.domain.approve(self.action,ttl=-1),'alpha')['allowed'])
    def test_missing(self):self.assertFalse(self.domain.execute(self.action,'missing','alpha')['allowed'])
    def test_current_version(self):
        with self.domain.db() as db:db.execute("UPDATE objects SET version='2'")
        self.assertEqual(self.execute()['reason'],'state_changed')
    def test_current_policy(self):
        with self.domain.db() as db:db.execute("UPDATE policy SET version='2'")
        self.assertFalse(self.execute()['allowed'])
    def test_retry_persisted_after_reopen(self):
        first=self.execute();reopened=a.Domain(self.domain.path)
        second=reopened.execute(self.action,self.grant,'alpha')
        self.assertEqual(first['receipt'],second['receipt']);self.assertEqual(second['reason'],'replayed')
    def test_new_approval_does_not_reuse_id_for_another_action(self):
        self.execute();changed={**self.action,'body':'alterado'};grant=self.domain.approve(changed)
        self.assertEqual(self.domain.execute(changed,grant,'alpha')['reason'],'idempotency_conflict')
    def test_compensation_preserves_original(self):
        receipt=self.execute()['receipt'];self.assertTrue(self.domain.compensate(receipt,'alpha'))
        self.assertTrue(self.domain.compensate(receipt,'alpha'))
        with self.domain.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM receipts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM compensations').fetchone()[0],1)
    def test_foreign_compensation(self):self.assertFalse(self.domain.compensate(self.execute()['receipt'],'beta'))
    def test_extra_field_rejected(self):
        with self.assertRaises(ValueError):a.fingerprint({**self.action,'role':'admin'})
    def test_canonical_key_order(self):self.assertEqual(a.fingerprint(self.action),a.fingerprint(dict(reversed(list(self.action.items())))))


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.auth=d.Authority(Path(self.temp.name)/'issuer.sqlite','http://127.0.0.1:9999')
        self.root=self.auth.issue()
    def child(self,**changes):
        p=dict(token=self.root,actor='broker',target='domain',scope=['read'],resources=['alpha_contract'],next_actor='reader')
        p.update(changes);return self.auth.delegate(**p)
    def test_legitimate_chain(self):self.assertEqual(self.auth.validate(self.child(),'domain')['sub'],'user_alpha')
    def test_scope_escalation(self):
        with self.assertRaises(PermissionError):self.child(scope=['write'])
    def test_resource_escalation(self):
        with self.assertRaises(PermissionError):self.child(resources=['beta_contract'])
    def test_audience_escalation(self):
        with self.assertRaises(PermissionError):self.child(target='other')
    def test_workload_identity(self):
        with self.assertRaises(PermissionError):self.child(actor='analyzer')
    def test_no_expiry_extension(self):
        child=self.child(ttl=1000);self.assertLessEqual(self.auth.validate(child)['exp'],self.auth.validate(self.root)['exp'])
    def test_wrong_audience(self):
        with self.assertRaises(jwt.InvalidAudienceError):self.auth.validate(self.child(),'other')
    def test_signature(self):
        child=self.child()
        with self.assertRaises(jwt.InvalidTokenError):self.auth.validate(child.rsplit('.',1)[0]+'.'+'A'*342)
    def test_root_revocation_hits_descendant(self):
        child=self.child();self.auth.revoke(self.auth.validate(self.root)['jti'])
        with self.assertRaises(jwt.InvalidTokenError):self.auth.validate(child)
    def test_revoked_parent_cannot_issue(self):
        self.auth.revoke(self.auth.validate(self.root)['jti'])
        with self.assertRaises(jwt.InvalidTokenError):self.child()
    def test_second_hop_bound(self):
        child=self.child();grand=self.auth.delegate(child,'reader','domain',['read'],['alpha_contract'],'analyzer')
        self.assertEqual(self.auth.validate(grand)['depth'],0)
        with self.assertRaises(PermissionError):self.auth.delegate(grand,'analyzer','domain',['read'],['alpha_contract'],'reader')
    def test_child_revocation_preserves_parent(self):
        child=self.child();self.auth.revoke(self.auth.validate(child)['jti'])
        self.assertEqual(self.auth.validate(self.root)['depth'],2)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.receiver=t.Receiver(Path(self.temp.name)/'receiver.sqlite')
        self.task=Task(id='t1',context_id='ctx1',status=TaskStatus(state=TaskState.TASK_STATE_WORKING))
        self.receiver.register(self.task,'alpha');self.event=StreamResponse(task=t.completed(self.task,'alpha'))
    def accept(self):return self.receiver.accept('strict','t1',self.event)
    def test_legitimate(self):self.assertEqual(self.accept(),(200,'consumed'))
    def test_task_swap(self):self.event.task.id='other';self.assertEqual(self.accept(),(403,'binding'))
    def test_context_swap(self):self.event.task.context_id='other';self.assertEqual(self.accept(),(403,'binding'))
    def test_tenant_swap(self):self.event.task.artifacts[0].metadata['tenant']='beta';self.assertEqual(self.accept(),(403,'binding'))
    def test_artifact_swap(self):self.event.task.artifacts[0].metadata['sourceTaskId']='other';self.assertEqual(self.accept(),(403,'binding'))
    def test_resource_swap(self):self.event.task.artifacts[0].metadata['resource']='beta_contract';self.assertEqual(self.accept(),(403,'binding'))
    def test_nonterminal(self):self.event.task.status.state=TaskState.TASK_STATE_WORKING;self.assertEqual(self.accept(),(403,'binding'))
    def test_late_canceled(self):self.receiver.cancel('t1');self.assertEqual(self.accept(),(409,'terminal_local_state'))
    def test_duplicate(self):self.accept();self.assertEqual(self.accept(),(200,'duplicate'))
    def test_conflict(self):self.accept();self.event.task.artifacts[0].parts[0].text='changed';self.assertEqual(self.accept(),(409,'conflict'))
    def test_incomplete_artifact(self):del self.event.task.artifacts[:];self.assertEqual(self.accept(),(400,'not_complete_task'))
    def test_catalog_description_is_bound(self):
        before={'name':'read','description':'old','inputSchema':{'type':'object'}}
        self.assertNotEqual(m.catalog_hash(before),m.catalog_hash({**before,'description':'new'}))


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        for name,module in [('l17',a),('l18',d),('l19',m),('l20',t)]:module.run(cls.root/name)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def altered(self,name):
        out=self.root/(self._testMethodName+'_'+name);shutil.copytree(self.root/name,out)
        return out,json.loads((out/'results.json').read_text(encoding='utf-8'))
    def test_four_integrations(self):
        for name,module in [('l17',a),('l18',d),('l19',m),('l20',t)]:self.assertTrue(module.verify(self.root/name)['passed'])
    def test_approval_false_denial(self):
        out,r=self.altered('l17');r['rows'][0]['status']=403;write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):a.verify(out)
    def test_lost_compensation_evidence(self):
        out,_=self.altered('l17')
        with database(out/'strict.sqlite') as db:db.execute('DELETE FROM compensations')
        seal(out)
        with self.assertRaises(AssertionError):a.verify(out)
    def test_delegation_missing_receipt(self):
        out,_=self.altered('l18')
        with database(out/'consumer.sqlite') as db:db.execute('DELETE FROM receipts WHERE id=1')
        seal(out)
        with self.assertRaises(AssertionError):d.verify(out)
    def test_delegation_false_success(self):
        out,r=self.altered('l18');r['rows'][-1]['status']=200;write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):d.verify(out)
    def test_mcp_false_check(self):
        out,r=self.altered('l19');r['checks'][0]['passed']=False;write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):m.verify(out)
    def test_mcp_foreign_receipt(self):
        out,_=self.altered('l19')
        with database(out/'strict.sqlite') as db:db.execute("UPDATE receipts SET resource='beta_contract' WHERE id=1")
        seal(out)
        with self.assertRaises(AssertionError):m.verify(out)
    def test_a2a_false_callback_success(self):
        out,r=self.altered('l20');r['callbacks'][-1]['outcomes'][1]['status']=200;write(out/'results.json',r);seal(out)
        with self.assertRaises(AssertionError):t.verify(out)
    def test_a2a_missing_consumption(self):
        out,_=self.altered('l20')
        with database(out/'receiver.sqlite') as db:db.execute("DELETE FROM receipts WHERE profile='strict'")
        seal(out)
        with self.assertRaises(AssertionError):t.verify(out)
    def test_missing_catalog_is_incomplete(self):
        out,_=self.altered('l19');(out/'strict_catalogs.json').unlink()
        with self.assertRaises(AssertionError):m.verify(out)


if __name__=='__main__':unittest.main()
