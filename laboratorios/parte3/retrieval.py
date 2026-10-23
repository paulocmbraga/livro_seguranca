"""SQLite FTS5 e FAISS reais; vetores lexicais normalizados, não embeddings neurais."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from importlib.metadata import version

import faiss
import numpy as np

from .common import new_output, write, seal, integrity

DIM = 128


def tokens(text):
    return re.findall(r'[a-z0-9_]+', text.lower())


def embed(text):
    v = np.zeros(DIM, dtype='float32')
    for term in tokens(text):
        slot = int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], 'big') % DIM
        v[slot] += 1
    norm = np.linalg.norm(v)
    return v / norm if norm else v


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'origin.sqlite')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, tenant TEXT, text TEXT, version INT, active INT)')
        self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED, text)')
        self.db.execute('CREATE TABLE IF NOT EXISTS exposures(seq INTEGER PRIMARY KEY, case_id TEXT, principal TEXT, document INT, version INT, text TEXT)')
        self.lock = threading.RLock()
        self.cache = {}
        self.epoch = 0
        self.snapshot = []
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(DIM))

    def ingest(self, principal_tenant, doc_id, text, claimed_tenant=None):
        if type(doc_id) is not int or not text or len(text) > 4000:
            raise ValueError('Documento fora do contrato')
        old = self.db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
        if old and old['tenant'] != principal_tenant:
            raise PermissionError('Conector não pode alterar outro tenant')
        rev = old['version'] + 1 if old else 1
        # O corpo não pode conferir autoridade ao metadado de identidade.
        self.db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,1)',
                        (doc_id, principal_tenant, text, rev))
        self.db.commit()
        self.epoch += 1

    def rebuild(self):
        self.snapshot = [dict(r) for r in self.db.execute('SELECT * FROM documents WHERE active=1 ORDER BY id')]
        self.db.execute('DELETE FROM search')
        self.db.executemany('INSERT INTO search VALUES(?,?)', [(d['id'], d['text']) for d in self.snapshot])
        self.db.commit()
        self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(DIM))
        if self.snapshot:
            self.index.add_with_ids(np.stack([embed(d['text']) for d in self.snapshot]),
                                    np.array([d['id'] for d in self.snapshot], dtype='int64'))
        faiss.write_index(self.index, str(self.root / 'vectors.faiss'))
        write(self.root / 'chunks.json', self.snapshot)
        self.cache.clear()

    def allowed(self, tenant, item):
        row = self.db.execute('SELECT * FROM documents WHERE id=?', (item['id'],)).fetchone()
        return bool(row and row['active'] and row['tenant'] == tenant and row['version'] == item['version'])

    def rank(self, query, backend):
        if backend == 'fts':
            terms = tokens(query)
            if not terms:
                return []
            expression = ' OR '.join('"' + t + '"' for t in terms)
            ids = [int(r[0]) for r in self.db.execute(
                'SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search), CAST(id AS INT)', (expression,))]
        elif backend == 'faiss':
            if not self.snapshot:
                return []
            scores, raw = self.index.search(embed(query)[None, :], len(self.snapshot))
            ids = [int(i) for i, score in zip(raw[0], scores[0]) if i >= 0 and score > 0]
        else:
            raise ValueError('Backend desconhecido')
        by_id = {d['id']: d for d in self.snapshot}
        return [by_id[i] for i in ids]

    def query(self, tenant, query, backend='faiss', mode='strict', k=1):
        if mode not in {'strict', 'postfilter', 'weak'} or not 1 <= k <= 3:
            raise ValueError('Consulta fora do contrato')
        with self.lock:
            key = (query, backend) if mode == 'weak' else (tenant, query, backend, mode, k, self.epoch)
            if key in self.cache:
                return [dict(d) for d in self.cache[key]]
            candidates = self.rank(query, backend)
            if mode == 'strict':
                candidates = [d for d in candidates if self.allowed(tenant, d)][:k]
            elif mode == 'postfilter':
                candidates = [d for d in candidates[:k] if self.allowed(tenant, d)]
            else:
                candidates = candidates[:k]
            self.cache[key] = [dict(d) for d in candidates]
            return candidates

    def consume(self, case, tenant, items, strict=True):
        with self.lock:
            if strict and not all(self.allowed(tenant, item) for item in items):
                return {'status': 'stale_or_denied', 'ids': [], 'context': ''}
            for item in items:
                self.db.execute('INSERT INTO exposures(case_id,principal,document,version,text) VALUES(?,?,?,?,?)',
                                (case, tenant, item['id'], item['version'], item['text']))
            self.db.commit()
            return {'status': 'delivered', 'ids': [d['id'] for d in items],
                    'context': '\n'.join(d['text'] for d in items)}

    def revoke(self, doc_id):
        with self.lock:
            self.db.execute('UPDATE documents SET active=0,version=version+1 WHERE id=?', (doc_id,))
            self.db.commit()
            self.epoch += 1

    def purge(self, doc_id):
        self.db.execute('DELETE FROM documents WHERE id=?', (doc_id,))
        self.db.commit()
        self.rebuild()
        self.db.execute('VACUUM')

    def close(self):
        self.db.close()


def run(directory):
    out = new_output(directory)
    started = time.monotonic()
    rows = []
    for backend in ('fts', 'faiss'):
        store = Store(out / backend)
        try:
            store.ingest('alpha', 1, 'reembolso prazo comprovante procedimento MARCADOR_ALPHA')
            store.ingest('beta', 2, 'reembolso MARCADOR_BETA')
            store.rebuild()
            # Busca com contrato estrangeiro mais bem classificado.
            q = 'reembolso MARCADOR_BETA'
            for mode in ('weak', 'postfilter', 'strict'):
                items = store.query('alpha', q, backend, mode)
                rows.append({'case': backend + '_' + mode, 'backend': backend,
                             **store.consume(backend + '_' + mode, 'alpha', items, mode != 'weak')})
            # Aquecer cache com beta; alpha reutiliza chave fraca.
            store.query('beta', q, backend, 'weak')
            rows.append({'case': backend + '_cache_cross', 'backend': backend,
                         **store.consume(backend + '_cache_cross', 'alpha', store.query('alpha', q, backend, 'weak'), False)})
            staged = store.query('alpha', 'comprovante', backend, 'strict')
            store.revoke(1)
            rows.append({'case': backend + '_revoked_delivery', 'backend': backend,
                         **store.consume(backend + '_revoked_delivery', 'alpha', staged)})
            rows.append({'case': backend + '_stale_weak', 'backend': backend,
                         **store.consume(backend + '_stale_weak', 'alpha', staged, False)})
            rows.append({'case': backend + '_revoked_search', 'backend': backend,
                         **store.consume(backend + '_revoked_search', 'alpha', store.query('alpha', 'comprovante', backend))})
            # Índice permanece copiado até limpeza explícita.
            before = {'indexed': [d['id'] for d in store.snapshot], 'cache_entries': len(store.cache)}
            store.purge(1)
            reloaded = faiss.read_index(str(store.root / 'vectors.faiss'))
            after = {'indexed': [d['id'] for d in store.snapshot], 'cache_entries': len(store.cache),
                     'faiss_ntotal_after_reload': reloaded.ntotal,
                     'fts_old_hits': len(store.db.execute('SELECT id FROM search WHERE search MATCH ?', ('comprovante',)).fetchall())}
            rows.append({'case': backend + '_purge', 'backend': backend, 'before': before, 'after': after})
            # Contaminação autorizada: ACL não decide qualidade factual do documento.
            store.ingest('alpha', 3, 'reembolso prazo comprovante procedimento reembolso prazo comprovante procedimento INSTRUCAO_HOSTIL', claimed_tenant='beta')
            store.rebuild()
            items = store.query('alpha', 'procedimento', backend)
            rows.append({'case': backend + '_poisoned_authorized', 'backend': backend,
                         **store.consume(backend + '_poisoned_authorized', 'alpha', items)})
            try:
                store.ingest('alpha', 2, 'substituição proibida')
                raise AssertionError('Conector cruzou tenant')
            except PermissionError:
                rows.append({'case': backend + '_ingest_cross', 'backend': backend, 'status': 'denied'})
        finally:
            store.close()
    report = {'lab': 'L10', 'versions': {p: version(p) for p in ('faiss-cpu', 'numpy')},
              'sqlite': sqlite3.sqlite_version, 'dimensions': DIM, 'embedding': 'hashed_term_frequency_l2',
              'elapsed_seconds': round(time.monotonic()-started, 4), 'cases': rows,
              'limits': ['Exact exhaustive vector index; not neural embeddings or ANN.',
                         'Deletion covers active origin/index/cache, not audit/backups or prior contexts.']}
    write(out / 'results.json', report)
    seal(out)
    return verify(out)


def verify(directory):
    out = Path(directory)
    integrity(out)
    data = json.loads((out / 'results.json').read_text(encoding='utf-8'))
    rows = {r['case']: r for r in data['cases']}
    names = ('weak','postfilter','strict','cache_cross','revoked_delivery','stale_weak','revoked_search','purge','poisoned_authorized','ingest_cross')
    assert len(data['cases']) == len(rows) == 20
    assert set(rows) == {b+'_'+n for b in ('fts','faiss') for n in names}
    for b in ('fts','faiss'):
        assert rows[b+'_weak']['ids'] == [2]
        assert rows[b+'_cache_cross']['ids'] == [2]
        assert rows[b+'_postfilter']['ids'] == []
        assert rows[b+'_strict']['ids'] == [1]
        assert rows[b+'_revoked_delivery']['status'] == 'stale_or_denied'
        assert rows[b+'_stale_weak']['ids'] == [1]
        assert rows[b+'_revoked_search']['ids'] == []
        assert rows[b+'_purge']['after'] == {'indexed':[2],'cache_entries':0,'faiss_ntotal_after_reload':1,'fts_old_hits':0}
        assert rows[b+'_poisoned_authorized']['ids'] == [3]
        assert rows[b+'_ingest_cross']['status'] == 'denied'
        conn = sqlite3.connect('file:'+str((out/b/'origin.sqlite').resolve())+'?mode=ro', uri=True)
        try:
            observed = conn.execute('SELECT case_id,document,text FROM exposures ORDER BY seq').fetchall()
            expected = [(r['case'], i, r['context']) for r in data['cases'] if r['backend']==b for i in r.get('ids',[])]
            assert observed == expected
            assert conn.execute('SELECT id FROM documents ORDER BY id').fetchall() == [(2,),(3,)]
        finally:
            conn.close()
    return {'lab':'L10','cases':20,'integrity':True,'exposures_reconciled':10}
