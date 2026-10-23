"""Emissor de teste para identidades de serviço; não é um IdP de produção."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qs

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


class Authority:
    def __init__(self, issuer):
        self.issuer = issuer
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.key.public_key()
        self.clients = {t: secrets.token_urlsafe(32) for t in ('alpha', 'beta')}
        self.resources = {}
        self.events = []

    def issue(self, subject, audience, scope, **overrides):
        """Overrides pertencem ao gerador de fixtures negativas, não ao endpoint HTTP."""
        now = int(time.time())
        claims = dict(iss=self.issuer, sub=subject, client_id=subject, tenant=subject,
                      aud=audience, scope=scope, iat=now, exp=now+120, jti=secrets.token_hex(12))
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'm1-ephemeral'})

    def validate(self, token, audience, scope=None):
        claims = jwt.decode(token, self.public_key, algorithms=['RS256'],
                            issuer=self.issuer, audience=audience,
                            options={'require': ['iss', 'sub', 'aud', 'exp', 'iat', 'jti', 'tenant', 'scope']})
        if scope and scope not in claims['scope'].split():
            raise PermissionError('insufficient_scope')
        if claims['sub'] not in self.clients or claims['tenant'] != claims['sub']:
            raise jwt.InvalidTokenError('subject_binding')
        return claims

    def app(self):
        async def metadata(request):
            return JSONResponse({'issuer': self.issuer,
                'token_endpoint': self.issuer+'/token', 'jwks_uri': self.issuer+'/jwks',
                'grant_types_supported': ['client_credentials'],
                'token_endpoint_auth_methods_supported': ['client_secret_basic'],
                'scopes_supported': sorted(set(self.resources.values()))})
        async def jwks(request):
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.public_key))
            key.update(kid='m1-ephemeral', use='sig', alg='RS256')
            return JSONResponse({'keys': [key]})
        async def token(request):
            try:
                auth = request.headers.get('Authorization', '')
                if not auth.startswith('Basic '):
                    raise ValueError()
                client, secret = base64.b64decode(auth[6:], validate=True).decode().split(':', 1)
                if client not in self.clients or not hmac.compare_digest(secret, self.clients[client]):
                    raise ValueError()
            except (ValueError, UnicodeError):
                self.events.append({'operation': 'token', 'allowed': False, 'reason': 'invalid_client'})
                return JSONResponse({'error': 'invalid_client'}, 401)
            form = parse_qs((await request.body()).decode())
            audience = form.get('resource', [''])[0]
            scope = form.get('scope', [''])[0]
            if form.get('grant_type') != ['client_credentials']:
                return JSONResponse({'error': 'unsupported_grant_type'}, 400)
            if audience not in self.resources or scope != self.resources[audience]:
                self.events.append({'operation': 'token', 'allowed': False, 'reason': 'resource_or_scope'})
                return JSONResponse({'error': 'invalid_target'}, 400)
            bearer = self.issue(client, audience, scope)
            self.events.append({'operation': 'token', 'allowed': True, 'subject': client,
                                'audience': audience, 'scope': scope,
                                'token_sha256': hashlib.sha256(bearer.encode()).hexdigest()})
            return JSONResponse({'access_token': bearer, 'token_type': 'Bearer', 'expires_in': 120},
                                headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})
        return Starlette(routes=[Route('/.well-known/oauth-authorization-server', metadata),
                                 Route('/jwks', jwks), Route('/token', token, methods=['POST'])])
