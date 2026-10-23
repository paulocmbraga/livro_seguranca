"""Regressões de recurso, transação, evidência e utilidade da revisão L15."""
from pathlib import Path
from tempfile import TemporaryDirectory
import gc
import json
import sqlite3
import unittest
from unittest.mock import patch
from apoio_revisao import privacidade as lab
from apoio_revisao.common import seal

class Conexoes(unittest.TestCase):
    def test_contraprovacao_contexto_sqlite_nao_fecha(self):
        db=sqlite3.connect(':memory:')
        try:
            with db: db.execute('SELECT 1')
            self.assertEqual(db.execute('SELECT 1').fetchone(),(1,))
        finally: db.close()

    def test_fecha_e_confirma_transacao(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.sqlite'
            with lab.connection(path) as db:
                db.execute('CREATE TABLE x(value INTEGER)')
                db.execute('INSERT INTO x VALUES (7)')
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
            with lab.connection(path) as check:self.assertEqual(check.execute('SELECT * FROM x').fetchall(),[(7,)])

    def test_fecha_e_reverte_em_excecao(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.sqlite'
            with lab.connection(path) as db:db.execute('CREATE TABLE x(value INTEGER)')
            with self.assertRaisesRegex(RuntimeError,'falha'):
                with lab.connection(path) as db:
                    db.execute('INSERT INTO x VALUES (7)')
                    raise RuntimeError('falha')
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
            with lab.connection(path) as check:self.assertEqual(check.execute('SELECT * FROM x').fetchall(),[])

    def test_campanha_fecha_todas_sem_coleta_de_lixo(self):
        real_connect=sqlite3.connect
        connections=[]
        def track(*args,**kwargs):
            # Permite que o teste consulte, após o join, também as conexões
            # criadas pelo receptor. Sem isso, erro de thread mascararia vazamento.
            kwargs['check_same_thread']=False
            db=real_connect(*args,**kwargs);connections.append(db);return db
        enabled=gc.isenabled();gc.disable()
        try:
            with TemporaryDirectory() as tmp:
                with patch.object(lab.sqlite3,'connect',side_effect=track):
                    result=lab.run(Path(tmp)/'capture')
                self.assertEqual(result['provider_calls'],8)
                self.assertEqual(result['utility_preserved'],8)
                self.assertEqual(result['after_cleanup'],{'cache':0,'audit':8,'vault':0})
                self.assertGreaterEqual(len(connections),13)
                for db in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
                # A saída do TemporaryDirectory deve remover os bancos com as
                # referências fortes ainda vivas, sem gc.collect().
        finally:
            for db in connections:db.close()
            if enabled:gc.enable()

    def test_limpa_conexoes_quando_transformacao_falha(self):
        real_connect=sqlite3.connect;connections=[]
        def track(*args,**kwargs):
            db=real_connect(*args,**kwargs);connections.append(db);return db
        with TemporaryDirectory() as tmp:
            with patch.object(lab.sqlite3,'connect',side_effect=track),patch.object(lab,'transform',side_effect=ValueError('injetada')):
                with self.assertRaisesRegex(ValueError,'injetada'):lab.run(Path(tmp)/'capture')
            self.assertEqual(len(connections),2)
            for db in connections:
                with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_rejeita_resumo_adulterado_mesmo_com_hash_novo(self):
        with TemporaryDirectory() as tmp:
            out=Path(tmp)/'capture';lab.run(out)
            path=out/'results.json';data=json.loads(path.read_text(encoding='utf-8'))
            data['rows'][0]['utility_total']=999
            path.write_text(json.dumps(data),encoding='utf-8');seal(out)
            with self.assertRaises(AssertionError):lab.verify(out)

    def test_run_nao_sobrescreve_captura(self):
        with TemporaryDirectory() as tmp:
            out=Path(tmp)/'capture';lab.run(out)
            with self.assertRaises(FileExistsError):lab.run(out)

    def test_hash_detecta_bytes_adulterados(self):
        with TemporaryDirectory() as tmp:
            out=Path(tmp)/'capture';lab.run(out)
            with (out/'results.json').open('a',encoding='utf-8') as f:f.write(' ')
            with self.assertRaises(AssertionError):lab.verify(out)
