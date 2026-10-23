"""L07: promoção assinada e carregamento dos mesmos bytes verificados.

Chave privada efêmera em processo emissor separado. A ameaça controla somente
o diretório de distribuição, não o bootstrap, o emissor nem o verificador.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from .common import create, write, read, seal, integrity, canonical, sha

EXPECTED = {
    'approved_v2': 'loaded', 'replace_only': 'digest',
    'replace_with_hash': 'signature', 'self_signed': 'signature',
    'old_approved': 'version', 'expired': 'expired',
    'wrong_role': 'role', 'oversized': 'size',
    'signed_bad_schema': 'schema', 'return_authorized_v3': 'loaded',
}


def authority_main():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    print(base64.b64encode(public).decode(), flush=True)
    for line in sys.stdin:
        record = json.loads(line)
        payload = canonical(record)
        print(json.dumps({'signed': record,
                          'signature': base64.b64encode(key.sign(payload)).decode()}), flush=True)


@contextmanager
def signer():
    child = subprocess.Popen([sys.executable, '-m', 'laboratorios.parte2.supply', '--authority'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding='utf-8')
    try:
        public = base64.b64decode(child.stdout.readline().strip(), validate=True)
        def sign(record):
            child.stdin.write(json.dumps(record) + '\n'); child.stdin.flush()
            return json.loads(child.stdout.readline())
        yield public, sign, child.pid
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=5)
        error = child.stderr.read()[:500]
        child.stdout.close(); child.stderr.close()
        if child.returncode:
            raise RuntimeError('Emissor falhou: ' + error)


def load_verified(blob, envelope, pinned_public, minimum_version, now):
    if len(blob) > 4096:
        raise ValueError('size')
    try:
        Ed25519PublicKey.from_public_bytes(pinned_public).verify(
            base64.b64decode(envelope['signature'], validate=True), canonical(envelope['signed']))
    except (InvalidSignature, KeyError, TypeError, ValueError):
        raise ValueError('signature') from None
    m = envelope['signed']
    if m.get('role') != 'classifier-config' or m.get('name') != 'model.json':
        raise ValueError('role')
    if type(m.get('version')) is not int or m['version'] < minimum_version:
        raise ValueError('version')
    if not isinstance(m.get('expires'), int) or now >= m['expires']:
        raise ValueError('expired')
    if sha(blob) != m.get('sha256') or len(blob) != m.get('length'):
        raise ValueError('digest')
    # Só interpretar depois da autenticidade, integridade e política de promoção.
    try:
        model = json.loads(blob)
        if set(model) != {'threshold', 'labels'}:
            raise ValueError()
        if type(model['threshold']) not in (int, float) or not 0 <= model['threshold'] <= 1:
            raise ValueError()
        if model['labels'] != ['review', 'accept']:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('schema') from None
    return model


def run(path):
    out = create(path); now = int(time.time()); records = []
    good = canonical({'threshold': .8, 'labels': ['review', 'accept']})
    bad = canonical({'threshold': .01, 'labels': ['review', 'accept']})
    def manifest(blob, version=2, **extra):
        return dict(name='model.json', role='classifier-config', version=version,
                    expires=now + 3600, sha256=sha(blob), length=len(blob), **extra)
    with signer() as (public, sign, pid):
        approved = sign(manifest(good))
        forged = json.loads(json.dumps(approved)); forged['signed']['sha256'] = sha(bad)
        forged['signed']['length'] = len(bad)
        attacker = Ed25519PrivateKey.generate()
        self_signed = {'signed': forged['signed'],
            'signature': base64.b64encode(attacker.sign(canonical(forged['signed']))).decode(),
            'replacement_public_key': base64.b64encode(attacker.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw)).decode()}
        expired = manifest(good); expired['expires'] = now - 1
        role = manifest(good); role['role'] = 'prompt'
        broken = canonical({'threshold': 'execute', 'labels': ['review', 'accept']})
        trials = [
            ('approved_v2', good, approved), ('replace_only', bad, approved),
            ('replace_with_hash', bad, forged), ('self_signed', bad, self_signed),
            ('old_approved', good, sign(manifest(good, 1))),
            ('expired', good, sign(expired)), ('wrong_role', good, sign(role)),
            ('oversized', b'x' * 4097, approved),
            ('signed_bad_schema', broken, sign(manifest(broken))),
            # Retorno ao conteúdo antigo, com NOVA autorização monotônica.
            ('return_authorized_v3', good, sign(manifest(good, 3))),
        ]
        for case, blob, envelope in trials:
            directory = out/case; directory.mkdir()
            (directory/'artifact.json').write_bytes(blob)
            write(directory/'envelope.json', envelope)
            try:
                model = load_verified(blob, envelope, public, 2, now)
                outcome = 'loaded'
                receipt = {'artifact_sha256': sha(blob), 'threshold': model['threshold']}
            except ValueError as error:
                outcome = str(error); receipt = None
            records.append(dict(case=case, outcome=outcome, load_receipt=receipt))
        bootstrap = dict(public_key=base64.b64encode(public).decode(),
            fingerprint=sha(public), minimum_version=2, evaluated_at=now,
            signer_pid=pid, verifier_pid=__import__('os').getpid(),
            trusted_channel='pipe do processo emissor; fora da pasta adversarial',
            limit='Separação de processo, não isolamento contra administrador ou mesmo usuário.')
    write(out/'bootstrap.json', bootstrap); write(out/'results.json', records)
    write(out/'weak_hash_check.json', {'artifact_hash': sha(bad), 'provided_hash': sha(bad),
                                     'accepted': True, 'proves_origin': False})
    seal(out, 'L07'); return verify(out)


def verify(path):
    out = Path(path); integrity(out, 'L07'); bootstrap = read(out/'bootstrap.json')
    public = base64.b64decode(bootstrap['public_key'], validate=True)
    if sha(public) != bootstrap['fingerprint']:
        raise ValueError('Bootstrap inconsistente')
    rows = read(out/'results.json')
    if len(rows) != len(EXPECTED) or {r['case'] for r in rows} != set(EXPECTED):
        raise ValueError('Campanha incompleta')
    for row in rows:
        case = row['case']; blob = (out/case/'artifact.json').read_bytes()
        try:
            model = load_verified(blob, read(out/case/'envelope.json'), public,
                                  bootstrap['minimum_version'], bootstrap['evaluated_at'])
            outcome = 'loaded'
            receipt = dict(artifact_sha256=sha(blob), threshold=model['threshold'])
        except ValueError as error:
            outcome = str(error); receipt = None
        if outcome != EXPECTED[case] or row != dict(case=case, outcome=outcome, load_receipt=receipt):
            raise ValueError('Reexecução divergente: ' + case)
    return dict(cases=len(rows), loaded=2, refused_before_load=8,
                limit='Reverificação no instante capturado; não renova uma promoção expirada.')


if __name__ == '__main__' and '--authority' in sys.argv:
    authority_main()
