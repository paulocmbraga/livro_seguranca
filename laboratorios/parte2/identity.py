"""Emissor de fixtures RS256. Não implementa um provedor OAuth/OIDC."""
import secrets
import time
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = 'urn:livro:emissor-local'
AUDIENCE = 'urn:livro:documentos'
ACCOUNTS = {
    'ana': {'tenant': 'alpha', 'role': 'reader'},
    'bia': {'tenant': 'beta', 'role': 'reader'},
    'auditor': {'tenant': 'alpha', 'role': 'auditor'},
}


class Authority:
    def __init__(self):
        self.keys = {}; self.active = None; self.trusted = {}; self.revoked = set()
        self.rotate('k1')

    def rotate(self, kid):
        if kid in self.keys:
            raise ValueError('kid já utilizado')
        self.keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.trusted[kid] = self.keys[kid].public_key()
        self.active = kid

    def issue(self, subject='ana', **overrides):
        now = int(time.time())
        claims = dict(iss=ISSUER, aud=AUDIENCE, sub=subject,
                      tenant=ACCOUNTS[subject]['tenant'], iat=now, nbf=now,
                      exp=now + 120, jti=secrets.token_hex(16),
                      scope='read', token_use='access')
        claims.update(overrides)
        return jwt.encode(claims, self.keys[self.active], algorithm='RS256',
                          headers={'kid': self.active, 'typ': 'at+jwt'})

    def validate(self, token, weak=False):
        header = jwt.get_unverified_header(token)
        # kid é apenas índice numa tabela local; nunca URL/caminho fornecido pelo token.
        if header.get('kid') not in self.trusted:
            raise jwt.InvalidTokenError('unknown_key')
        if header.get('typ') != 'at+jwt':
            raise jwt.InvalidTokenError('wrong_type')
        claims = jwt.decode(token, self.trusted[header['kid']], algorithms=['RS256'],
            issuer=ISSUER, audience=AUDIENCE,
            options={'verify_aud': not weak, 'require':
                     ['iss', 'aud', 'sub', 'tenant', 'iat', 'nbf', 'exp', 'jti',
                      'scope', 'token_use']})
        if claims['token_use'] != 'access':
            raise jwt.InvalidTokenError('wrong_use')
        account = ACCOUNTS.get(claims['sub'])
        if account is None or claims['tenant'] != account['tenant']:
            raise jwt.InvalidTokenError('subject_binding')
        if not isinstance(claims['scope'], str) or not isinstance(claims['jti'], str):
            raise jwt.InvalidTokenError('claim_type')
        if claims['jti'] in self.revoked:
            raise jwt.InvalidTokenError('revoked')
        return claims

    def revoke(self, token):
        claims = self.validate(token)
        self.revoked.add(claims['jti'])


def safe_telemetry(event):
    # Allowlist tipada: não serializar headers, prompt, body nem exceção bruta.
    return {key: event[key] for key in ('case', 'status', 'reason')
            if key in event and isinstance(event[key], (str, int))}
