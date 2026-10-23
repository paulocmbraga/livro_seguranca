import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

import numpy as np

from laboratorios.parte3 import retrieval,memory
from laboratorios.parte3.transforms import text_from_html,render
from laboratorios.parte3.common import PROJECT,sha


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=retrieval.Store(self.temp.name)
        self.store.ingest('alpha',1,'reembolso prazo comprovante MARCADOR_ALPHA')
        self.store.ingest('beta',2,'reembolso MARCADOR_BETA')
        self.store.rebuild()
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def test_principal_controls_ingestion(self):
        self.store.ingest('alpha',3,'manual',claimed_tenant='beta')
        self.assertEqual(self.store.db.execute('SELECT tenant FROM documents WHERE id=3').fetchone()[0],'alpha')
    def test_connector_cannot_replace_foreign(self):
        with self.assertRaises(PermissionError): self.store.ingest('alpha',2,'troca')
    def test_vector_is_normalized(self): self.assertAlmostEqual(float(np.linalg.norm(retrieval.embed('a a b'))),1,places=6)
    def test_empty_vector(self): self.assertEqual(float(np.linalg.norm(retrieval.embed('!!!'))),0)
    def test_rank_exposes_poison_without_authorization(self):
        self.assertEqual(self.store.rank('MARCADOR_BETA','faiss')[0]['id'],2)
    def test_prefilter_keeps_relevant_candidate(self):
        for backend in ('fts','faiss'):
            self.assertEqual([d['id'] for d in self.store.query('alpha','reembolso MARCADOR_BETA',backend)],[1])
    def test_postfilter_loses_topk_utility(self):
        for backend in ('fts','faiss'):
            self.assertEqual(self.store.query('alpha','reembolso MARCADOR_BETA',backend,'postfilter'),[])
    def test_cache_does_not_leak_between_tenants(self):
        self.store.query('beta','reembolso','faiss')
        self.assertEqual([d['id'] for d in self.store.query('alpha','reembolso','faiss')],[1])
    def test_query_epoch_after_revoke(self):
        self.store.query('alpha','comprovante'); self.store.revoke(1)
        self.assertEqual(self.store.query('alpha','comprovante'),[])
    def test_revoked_between_query_and_consumption(self):
        staged=self.store.query('alpha','comprovante'); self.store.revoke(1)
        self.assertEqual(self.store.consume('cut','alpha',staged)['status'],'stale_or_denied')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM exposures').fetchone()[0],0)
    def test_replacement_invalidates_old_context(self):
        staged=self.store.query('alpha','comprovante')
        self.store.ingest('alpha',1,'texto atualizado')
        self.assertEqual(self.store.consume('cut','alpha',staged)['status'],'stale_or_denied')
    def test_purge_clears_derivatives(self):
        self.store.query('alpha','comprovante'); self.store.purge(1)
        self.assertEqual(self.store.cache,{})
        self.assertEqual(self.store.index.ntotal,1)
        self.assertEqual(self.store.rank('comprovante','fts'),[])
    def test_invalid_backend(self):
        with self.assertRaises(ValueError): self.store.query('alpha','x','invented')
    def test_invalid_limit(self):
        with self.assertRaises(ValueError): self.store.query('alpha','x',k=0)
    def test_cache_respects_requested_cardinality(self):
        self.store.ingest('alpha',3,'reembolso prazo'); self.store.rebuild()
        self.assertEqual(len(self.store.query('alpha','reembolso',k=1)),1)
        self.assertEqual(len(self.store.query('alpha','reembolso',k=2)),2)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'memory.sqlite'
        self.m=memory.Memory(self.path,True); self.m.source('doc')
        self.identity=('alpha','ana','s1')
        self.item={'id':'m1','kind':'fact','text':'preferencia portugues','source':'doc','version':1,'expires':100}
    def tearDown(self): self.m.close(); self.temp.cleanup()
    def promote(self): self.m.promote(self.identity,self.item,approved=True)
    def test_unapproved_candidate_stays_pending(self):
        self.assertFalse(self.m.promote(self.identity,self.item))
        self.assertEqual(self.m.recall('x',self.identity,'preferencia',1),[])
    def test_instruction_cannot_be_promoted_by_flag(self):
        self.assertFalse(self.m.promote(self.identity,{**self.item,'kind':'action'},approved=True))
    def test_stale_source_cannot_be_promoted(self):
        self.m.source('doc',2)
        self.assertFalse(self.m.promote(self.identity,self.item,approved=True))
    def test_new_session_preserves_owner_memory(self):
        self.promote(); self.m.close(); self.m=memory.Memory(self.path,True)
        self.assertEqual(len(self.m.recall('x',('alpha','ana','s2'),'preferencia',10)),1)
    def test_same_tenant_other_user_cannot_read(self):
        self.promote(); self.assertEqual(self.m.recall('x',('alpha','carlos','s2'),'preferencia',10),[])
    def test_foreign_tenant_cannot_read(self):
        self.promote(); self.assertEqual(self.m.recall('x',('beta','ana','s2'),'preferencia',10),[])
    def test_memory_is_data_not_system(self):
        self.promote(); self.assertEqual(self.m.recall('x',self.identity,'preferencia',10)[0]['role'],'tool')
    def test_expiry_rechecked_on_cache_hit(self):
        self.promote(); self.m.recall('x',self.identity,'preferencia',10)
        self.assertEqual(self.m.recall('y',self.identity,'preferencia',100),[])
    def test_revocation_rechecked_on_cache_hit(self):
        self.promote(); self.m.recall('x',self.identity,'preferencia',10); self.m.source('doc',2,0)
        self.assertEqual(self.m.recall('y',self.identity,'preferencia',11),[])
    def test_lineage_purge_cascades(self):
        self.promote(); self.m.promote(self.identity,{**self.item,'id':'m2','parent':'m1'},approved=True)
        self.assertEqual(self.m.purge('m1'),['m1','m2'])
    def test_purge_does_not_claim_audit_erasure(self):
        self.promote(); self.m.recall('x',self.identity,'preferencia',10); self.m.purge('m1')
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM recalls').fetchone()[0],1)
    def test_visible_conversation_is_separate(self):
        self.promote(); self.m.db.execute('DELETE FROM conversations'); self.m.db.commit()
        self.assertEqual(len(self.m.recall('x',self.identity,'preferencia',10)),1)


class TransformationTests(unittest.TestCase):
    def test_hidden_html_is_in_parser_output(self):
        self.assertIn('hostil',text_from_html('<span style="display:none">hostil</span>'))
    def test_entities_are_decoded(self): self.assertEqual(text_from_html('<p>A &amp; B</p>'),'A & B')
    def test_image_is_actual_png(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'x.png'; render('conteudo sintetico',path)
            self.assertTrue(path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
    def test_reserve_has_four_families_and_balanced_labels(self):
        c=json.loads((PROJECT/'materiais/parte3/rag_reserva.json').read_text(encoding='utf-8'))
        self.assertEqual(len(c['cases']),8)
        self.assertEqual(len({r['family'] for r in c['cases']}),4)
        self.assertEqual(sum(r['hostile'] for r in c['cases']),4)


class IntegrationTests(unittest.TestCase):
    def test_real_indices_and_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(retrieval.run(Path(d)/'run')['cases'],20)
    def test_persisted_sequences_and_http_destination(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(memory.run(Path(d)/'run')['receipts_reconciled'],3)
    def test_capture_loss_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'run'; retrieval.run(out); (out/'fts/chunks.json').unlink()
            with self.assertRaises(ValueError): retrieval.verify(out)


if __name__=='__main__': unittest.main()
