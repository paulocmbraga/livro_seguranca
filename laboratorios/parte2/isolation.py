"""L08: Docker Linux, rede de bancada interna e recursos com nomes exclusivos.

Nenhum contêiner alheio é alterado. Não usa privileged, socket Docker montado
ou bind mount do host. O controlador tem autoridade Docker; o executor não.
"""
import json
from pathlib import Path
import subprocess
import time
import uuid
from .common import PROJECT, create, write, read, seal, integrity

BASE = 'python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2'


def docker(*args, timeout=60, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True,
                            encoding='utf-8', timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr[:2000] or result.stdout[:2000])
    return result


def run(path):
    out = create(path); prefix = 'livro-l08-' + uuid.uuid4().hex[:10]
    image = prefix + ':local'; net = prefix + '-net'; receiver = prefix + '-receiver'
    names = []; created_net = False; built = False; started = time.monotonic()
    report = {'engine': json.loads(docker('version', '--format', '{{json .Server}}').stdout),
              'base_image': BASE, 'profiles': {}, 'extra': {}, 'commands': []}
    try:
        docker('image', 'inspect', BASE)  # Faltar base é erro de ambiente, nunca defesa.
        build = docker('build', '--network', 'none', '-t', image,
                       str(PROJECT/'materiais/parte2/runtime'), timeout=120)
        built = True
        (out/'build.log').write_text(build.stdout + build.stderr, encoding='utf-8')
        report['image_id'] = docker('image', 'inspect', image, '--format', '{{.Id}}').stdout.strip()
        docker('network', 'create', '--internal', net); created_net = True
        docker('run', '-d', '--name', receiver, '--network', net, '--memory', '64m',
               '--cpus', '.5', '--pids-limit', '32', '--read-only', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--user', '10001:10001',
               image, 'python', '/lab/receiver.py'); names.append(receiver)
        address = json.loads(docker('inspect', receiver).stdout)[0]['NetworkSettings']['Networks'][net]['IPAddress']
        # Aguarda prontidão do serviço por conexão local dentro do seu contêiner.
        ready = False
        for _ in range(20):
            probe = docker('exec', receiver, 'python', '-c',
                "import socket; socket.create_connection(('127.0.0.1',8080),1).close()", check=False)
            if probe.returncode == 0:
                ready = True; break
            time.sleep(.1)
        if not ready:
            raise RuntimeError('Destino não ficou pronto')

        def execute(profile, command=None, memory='128m', wall=20):
            name = prefix + '-' + profile; restricted = profile != 'permissive'
            args = ['create', '--name', name, '--network', 'none' if restricted else net,
                    '--memory', memory, '--memory-swap', memory, '--cpus', '.5',
                    '--pids-limit', '16' if restricted else '64',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--user', '10001:10001' if restricted else '0:0',
                    '--tmpfs', '/tmp:rw,noexec,nosuid,size=8m' if restricted else '/tmp:rw,noexec,nosuid,size=32m',
                    '-e', 'RECEIVER=' + address, '-e', 'PROFILE=' + profile]
            if restricted:
                args.append('--read-only')
            args += [image, 'python', '/lab/probe.py'] + ([command] if command else [])
            report['commands'].append(args)
            docker(*args); names.append(name)
            wall_start = time.monotonic(); timed_out = False
            try:
                result = docker('start', '-a', name, timeout=wall, check=False)
            except subprocess.TimeoutExpired:
                timed_out = True; docker('kill', name)
                result = docker('logs', name, check=False)
            info = json.loads(docker('inspect', name).stdout)[0]
            entry = dict(stdout=result.stdout, stderr=result.stderr, state=info['State'],
                         host_config={k: info['HostConfig'][k] for k in
                         ('ReadonlyRootfs', 'NetworkMode', 'Memory', 'MemorySwap',
                          'NanoCpus', 'PidsLimit', 'CapDrop', 'SecurityOpt', 'Tmpfs')},
                         user=info['Config']['User'], mounts=info['Mounts'],
                         elapsed_seconds=time.monotonic() - wall_start, timeout=timed_out)
            return entry

        for profile in ('permissive', 'restricted'):
            entry = execute(profile)
            if entry['state']['ExitCode'] or entry['timeout']:
                raise RuntimeError('Sonda não terminou: ' + profile)
            entry['probe'] = json.loads(entry['stdout']); report['profiles'][profile] = entry
        report['extra']['memory'] = execute('memory', 'memory', memory='64m')
        report['extra']['watchdog'] = execute('watchdog', 'spin', wall=2)
        report['receiver_receipts'] = [json.loads(line) for line in
                                      docker('logs', receiver).stdout.splitlines() if line.strip()]
    finally:
        for name in reversed(names):
            docker('rm', '-f', name, check=False)
        if created_net:
            docker('network', 'rm', net, check=False)
        if built:
            docker('image', 'rm', image, check=False)
        report['cleanup'] = {
            'containers_remaining': docker('ps', '-aq', '--filter', 'name=' + prefix).stdout.split(),
            'network_remaining': docker('network', 'ls', '-q', '--filter', 'name=' + net).stdout.split(),
            'image_remaining': docker('image', 'ls', '-q', image).stdout.split()}
        report['elapsed_seconds'] = time.monotonic() - started
        write(out/'results.json', report)
    validate(report); seal(out, 'L08'); return verify(out)


def validate(report):
    expected = {'public_read', 'private_read', 'root_write', 'tmp_small',
                'tmp_quota', 'direct_network', 'pids'}
    for profile, item in report['profiles'].items():
        probe = item['probe']; rows = probe['records']; indexed = {r['case']: r for r in rows}
        if len(rows) != 7 or set(indexed) != expected:
            raise ValueError('Sonda incompleta')
        if probe['children_remaining'] or item['state']['Running']:
            raise ValueError('Processo ainda ativo')
        for case in expected:
            want = 'allowed' if profile == 'permissive' or case in ('public_read', 'tmp_small') else 'denied'
            if indexed[case]['outcome'] != want:
                raise ValueError(f'Fronteira divergente: {profile}/{case}')
        if profile == 'restricted':
            if probe['uid'] != 10001 or not item['host_config']['ReadonlyRootfs']:
                raise ValueError('Identidade/filesystem incorretos')
            if item['host_config']['NetworkMode'] != 'none' or item['mounts']:
                raise ValueError('Rede/montagem inesperada')
            if probe['cgroup']['memory.max'] != '134217728' or probe['cgroup']['pids.max'] != '16':
                raise ValueError('Quotas não efetivas no cgroup')
            quota, period = map(int, probe['cgroup']['cpu.max'].split())
            if quota / period != .5:
                raise ValueError('Quota CPU não efetiva')
            for case, number in [('private_read', 13), ('root_write', 30), ('tmp_quota', 28), ('pids', 11)]:
                if indexed[case]['errno'] != number:
                    raise ValueError('Erro não corresponde à fronteira: ' + case)
            if indexed['direct_network']['errno'] not in (101, 113):
                raise ValueError('Rede falhou por motivo distinto de isolamento')
    if set(report['profiles']) != {'permissive', 'restricted'}:
        raise ValueError('Falta uma variante')
    if report['receiver_receipts'] != [{'path': '/hit/permissive', 'received': True}]:
        raise ValueError('Destino diverge')
    if not report['extra']['memory']['state']['OOMKilled']:
        raise ValueError('Limite de memória não observado')
    if not report['extra']['watchdog']['timeout']:
        raise ValueError('Watchdog não exercitado')
    if any(report['cleanup'].values()):
        raise ValueError('Limpeza incompleta')


def verify(path):
    out = Path(path); integrity(out, 'L08'); report = read(out/'results.json'); validate(report)
    return dict(profiles=2, direct_probes=14, additional_probes=2,
                forbidden_receipts_restricted=0, cleanup=True,
                limits='Contêiner Linux no Docker Desktop/WSL2; não testa escape de kernel nem hipervisor.')
