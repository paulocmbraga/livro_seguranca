"""Regressões de fronteiras: não dependem de modelo nem de API paga."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from laboratorios.m1.auth import Authority
from laboratorios.m1.inference import Adapter, decode
from laboratorios.l09.llm import InferenceError
from laboratorios.l00.artifacts import checked_target
from laboratorios.m1.common import seal, verify


class Credentials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issuer = Authority('http://127.0.0.1:12345')
        cls.audience = 'http://127.0.0.1:23456/mcp'

    def token(self, **changes):
        return self.issuer.issue('alpha', self.audience, 'contracts:read', **changes)

    def test_valid_subject_comes_from_signature(self):
        self.assertEqual(self.issuer.validate(self.token(), self.audience)['tenant'], 'alpha')

    def test_wrong_audience(self):
        with self.assertRaises(jwt.InvalidAudienceError):
            self.issuer.validate(self.token(), 'another-resource')

    def test_wrong_issuer(self):
        with self.assertRaises(jwt.InvalidIssuerError):
            self.issuer.validate(self.token(iss='another-issuer'), self.audience)

    def test_expired_token(self):
        with self.assertRaises(jwt.ExpiredSignatureError):
            self.issuer.validate(self.token(exp=int(time.time())-1), self.audience)

    def test_missing_scope(self):
        with self.assertRaises(PermissionError):
            self.issuer.validate(self.token(), self.audience, 'tasks:operate')

    def test_subject_tenant_mismatch(self):
        with self.assertRaises(jwt.InvalidTokenError):
            self.issuer.validate(self.token(tenant='beta'), self.audience)

    def test_wrong_signing_key(self):
        attacker = Authority(self.issuer.issuer)
        with self.assertRaises(jwt.InvalidSignatureError):
            self.issuer.validate(attacker.issue('alpha', self.audience, 'contracts:read'), self.audience)


def response(finish='stop', content=None):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content or json.dumps({
        'resource': 'alpha_contract', 'tenant': 'alpha', 'destination': 'portal_alpha'})}}]}


class InferenceContract(unittest.TestCase):
    def test_truncated_is_error(self):
        with self.assertRaises(InferenceError):
            decode(response('length'))

    def test_malformed_json_is_error(self):
        with self.assertRaises(InferenceError):
            decode(response(content='{'))

    def test_forbidden_destination_is_schema_error(self):
        with self.assertRaises(InferenceError):
            decode(response(content='{"resource":"x","tenant":"alpha","destination":"https://remote"}'))

    def test_budget_and_cache(self):
        adapter = Adapter('http://127.0.0.1:1', 'test', max_calls=1)
        with patch('laboratorios.m1.inference.http', return_value=response()) as server:
            adapter.propose('same', [], 'alpha', 0)
            _, cached = adapter.propose('same', [], 'alpha', 0)
            self.assertTrue(cached['cache_hit'])
            with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
                adapter.propose('different', [], 'alpha', 0)
            self.assertEqual(server.call_count, 1)

    def test_failed_response_is_not_retried_or_called_blocked(self):
        adapter = Adapter('http://127.0.0.1:1', 'test', max_calls=1)
        with patch('laboratorios.m1.inference.http', return_value=response(content='{')) as server:
            for _ in range(2):
                with self.assertRaises(InferenceError):
                    adapter.propose('same', [], 'alpha', 0)
            self.assertEqual(server.call_count, 1)
            self.assertEqual(len(adapter.ledger), 1)

    def test_wall_clock_budget(self):
        adapter = Adapter('http://127.0.0.1:1', 'test', max_seconds=-1)
        with self.assertRaisesRegex(RuntimeError, 'budget_exhausted'):
            adapter.propose('same', [], 'alpha', 0)


class Evidence(unittest.TestCase):
    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                checked_target(Path(folder), '../outside')

    def test_changed_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)/'data.json'
            data.write_text('{}')
            seal(folder)
            self.assertTrue(verify(folder)['integrity'])
            data.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'Integridade'):
                verify(folder)


if __name__ == '__main__':
    unittest.main()
