"""Contratos e integrações: respostas HTTP e consequências, não cópias de saída."""
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from laboratorios.parte2.identity import Authority, safe_telemetry
from laboratorios.parte2.service import State, server, call
from laboratorios.parte2.access_labs import l05, l06, summarize_access
from laboratorios.parte2.common import canonical, sha, read
from laboratorios.parte2.supply import load_verified, run as supply_run, verify as supply_verify
from laboratorios.parte2.common import PROJECT
from laboratorios.parte2.isolation import validate as validate_isolation


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Authority()

    def test_valid_subject(self):
        self.assertEqual(self.a.validate(self.a.issue())['sub'], 'ana')

    def test_wrong_audience(self):
        with self.assertRaises(jwt.InvalidAudienceError):
            self.a.validate(self.a.issue(aud='urn:another'))

    def test_wrong_issuer(self):
        with self.assertRaises(jwt.InvalidIssuerError):
            self.a.validate(self.a.issue(iss='urn:another'))

    def test_expiration(self):
        with self.assertRaises(jwt.ExpiredSignatureError):
            self.a.validate(self.a.issue(exp=int(time.time()) - 10))

    def test_not_yet_valid(self):
        with self.assertRaises(jwt.ImmatureSignatureError):
            self.a.validate(self.a.issue(nbf=int(time.time()) + 60))

    def test_subject_cannot_claim_other_tenant(self):
        with self.assertRaises(jwt.InvalidTokenError):
            self.a.validate(self.a.issue(tenant='beta'))

    def test_id_token_not_access_token(self):
        with self.assertRaises(jwt.InvalidTokenError):
            self.a.validate(self.a.issue(token_use='identity'))

    def test_missing_required_claim(self):
        now = int(time.time())
        token = jwt.encode({'iss': 'urn:livro:emissor-local', 'exp': now + 60},
                           self.a.keys['k1'], algorithm='RS256', headers={'kid': 'k1', 'typ': 'at+jwt'})
        with self.assertRaises(jwt.MissingRequiredClaimError):
            self.a.validate(token)

    def test_unknown_kid_does_not_fetch_url(self):
        token = jwt.encode({'sub': 'ana'}, self.a.keys['k1'], algorithm='RS256',
                           headers={'kid': 'https://example.invalid/key', 'typ': 'at+jwt'})
        with self.assertRaises(jwt.InvalidTokenError):
            self.a.validate(token)

    def test_algorithm_allowlist(self):
        token = jwt.encode({'sub': 'ana'}, '', algorithm='none', headers={'kid': 'k1', 'typ': 'at+jwt'})
        with self.assertRaises(jwt.InvalidAlgorithmError):
            self.a.validate(token)

    def test_revocation_specific_to_token(self):
        authority = Authority(); one = authority.issue(); two = authority.issue()
        authority.revoke(one)
        with self.assertRaises(jwt.InvalidTokenError):
            authority.validate(one)
        self.assertEqual(authority.validate(two)['sub'], 'ana')

    def test_rotation_overlap_and_retirement(self):
        authority = Authority(); old = authority.issue(); authority.rotate('k2')
        self.assertEqual(authority.validate(old)['sub'], 'ana')
        new = authority.issue(); del authority.trusted['k1']
        with self.assertRaises(jwt.InvalidTokenError):
            authority.validate(old)
        self.assertEqual(authority.validate(new)['sub'], 'ana')

    def test_telemetry_omits_arbitrary_fields(self):
        self.assertEqual(safe_telemetry({'case': 'a', 'status': 401, 'headers': {'x': 'secret'},
            'prompt': 'secret', 'new_field': 'secret'}), {'case': 'a', 'status': 401})


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.s = State(); self.a = self.s.authority

    def test_direct_alternate_route_is_mediated(self):
        with server(self.s) as url:
            r = call(url, self.a.issue('ana'), 'cross', 'b1', '/debug', tenant='beta', role='admin')
        self.assertEqual(r['status'], 403); self.assertEqual(self.s.reads, [])

    def test_valid_token_missing_scope(self):
        with server(self.s) as url:
            r = call(url, self.a.issue(scope='export'), 'scope')
        self.assertEqual(r['status'], 403); self.assertFalse(self.s.reads)

    def test_same_tenant_not_enough(self):
        with server(self.s) as url:
            r = call(url, self.a.issue(), 'restricted', 'a2')
        self.assertEqual(r['status'], 403)

    def test_auditor_operation(self):
        with server(self.s) as url:
            token = self.a.issue('auditor')
            self.assertEqual(call(url, token, 'read', 'a2')['status'], 200)
            self.assertEqual(call(url, token, 'export', 'a2', '/export')['status'], 403)

    def test_cache_other_identity(self):
        with server(self.s) as url:
            call(url, self.a.issue(), 'warm')
            r = call(url, self.a.issue('bia'), 'reuse')
        self.assertEqual(r['status'], 403); self.assertEqual(len(self.s.reads), 1)

    def test_revocation_before_cache(self):
        with server(self.s) as url:
            token = self.a.issue(); call(url, token, 'warm')
            self.s.revoke_grant('ana', 'a1')
            r = call(url, token, 'revoked')
        self.assertEqual(r['status'], 403)

    def test_unavailable_is_error_not_deny(self):
        with server(self.s) as url:
            token = self.a.issue(); call(url, token, 'warm')
            self.s.available = False; r = call(url, token, 'down')
        self.assertEqual(r['status'], 503); self.assertEqual(r['body']['reason'], 'policy_unavailable')

    def test_reject_missing_resource(self):
        with server(self.s) as url:
            r = call(url, self.a.issue(), 'absent', 'nonexistent')
        self.assertEqual(r['status'], 404)

    def test_empty_campaign_not_success(self):
        with self.assertRaises(ValueError):
            summarize_access([], [], [], {'case': 200})

    def test_response_without_read_not_success(self):
        with self.assertRaises(ValueError):
            summarize_access([{'case': 'x', 'status': 200}], [{'case': 'x', 'status': 200}], [], {'x': 200})

    def test_duplicate_case_rejected(self):
        with self.assertRaises(ValueError):
            summarize_access([{'case': 'x'}, {'case': 'x'}], [], [], {'x': 200})


class SupplyTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.blob = canonical({'threshold': .8, 'labels': ['review', 'accept']})
        self.m = dict(name='model.json', role='classifier-config', version=2, expires=2000,
                      sha256=sha(self.blob), length=len(self.blob))

    def envelope(self):
        return dict(signed=self.m, signature=base64.b64encode(self.key.sign(canonical(self.m))).decode())

    def test_valid_load(self):
        self.assertEqual(load_verified(self.blob, self.envelope(), self.public, 2, 1000)['threshold'], .8)

    def test_changed_bytes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'digest'):
            load_verified(self.blob + b' ', self.envelope(), self.public, 2, 1000)

    def test_replaced_hash_without_signature(self):
        envelope = self.envelope(); envelope['signed']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'signature'):
            load_verified(self.blob, envelope, self.public, 2, 1000)

    def test_signed_rollback(self):
        self.m['version'] = 1
        with self.assertRaisesRegex(ValueError, 'version'):
            load_verified(self.blob, self.envelope(), self.public, 2, 1000)

    def test_expiry_boundary(self):
        with self.assertRaisesRegex(ValueError, 'expired'):
            load_verified(self.blob, self.envelope(), self.public, 2, 2000)

    def test_signed_wrong_purpose(self):
        self.m['role'] = 'prompt'
        with self.assertRaisesRegex(ValueError, 'role'):
            load_verified(self.blob, self.envelope(), self.public, 2, 1000)

    def test_signed_invalid_schema(self):
        self.blob = b'{"threshold":true,"labels":["review","accept"]}'
        self.m.update(sha256=sha(self.blob), length=len(self.blob))
        with self.assertRaisesRegex(ValueError, 'schema'):
            load_verified(self.blob, self.envelope(), self.public, 2, 1000)

    def test_oversized_before_parse(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            load_verified(b'x' * 4097, {}, self.public, 2, 1000)


class CaptureIntegrationTests(unittest.TestCase):
    def test_l05_full_http(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(l05(Path(temp)/'run')['requests'], 16)

    def test_l06_matrix_and_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(l06(Path(temp)/'run')['requests'], 66)

    def test_l07_separate_signer_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'run'
            self.assertEqual(supply_run(out)['refused_before_load'], 8)
            (out/'approved_v2/artifact.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):
                supply_verify(out)


class IsolationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.r = read(PROJECT/'output/parte2_v01/l08/results.json')

    def test_canonical_kernel_capture(self):
        validate_isolation(self.r)

    def test_missing_probe_not_success(self):
        self.r['profiles']['restricted']['probe']['records'].pop()
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_receiver_contradicts_claim(self):
        self.r['receiver_receipts'].append({'path': '/hit/restricted', 'received': True})
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_wrong_errno_not_security(self):
        self.r['profiles']['restricted']['probe']['records'][1]['errno'] = 2
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_lost_utility_fails(self):
        self.r['profiles']['restricted']['probe']['records'][0]['outcome'] = 'denied'
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_cleanup_must_be_observed(self):
        self.r['cleanup']['containers_remaining'] = ['synthetic-survivor']
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_crash_without_oom_not_memory_proof(self):
        self.r['extra']['memory']['state']['OOMKilled'] = False
        with self.assertRaises(ValueError):
            validate_isolation(self.r)

    def test_ineffective_quota_rejected(self):
        self.r['profiles']['restricted']['probe']['cgroup']['memory.max'] = 'max'
        with self.assertRaises(ValueError):
            validate_isolation(self.r)


if __name__ == '__main__':
    unittest.main()
