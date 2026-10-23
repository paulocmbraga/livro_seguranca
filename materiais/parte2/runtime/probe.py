"""Sonda sintética: syscalls e socket diretos, sem wrapper de ferramentas."""
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import time

if len(sys.argv) > 1 and sys.argv[1] == 'memory':
    blocks = [bytearray(1024 * 1024) for _ in range(180)]
    print(json.dumps({'allocated_mib': len(blocks)})); sys.exit(0)
if len(sys.argv) > 1 and sys.argv[1] == 'spin':
    while True:
        pass

start = time.monotonic(); records = []


def attempt(case, action):
    try:
        result = action()
        records.append(dict(case=case, outcome='allowed', result=result))
    except OSError as error:
        records.append(dict(case=case, outcome='denied', errno=error.errno,
                            error=type(error).__name__))


attempt('public_read', lambda: Path('/lab/public.txt').read_text().strip())
attempt('private_read', lambda: Path('/lab/private.txt').read_text().strip())
attempt('root_write', lambda: Path('/etc/l08-test').write_text('SINTETICO'))
attempt('tmp_small', lambda: Path('/tmp/small').write_bytes(b'ok'))


def tmp_large():
    with open('/tmp/bounded-large', 'wb') as target:
        for _ in range(12):
            target.write(b'x' * (1024 * 1024))
    return 12


attempt('tmp_quota', tmp_large)


def network():
    with socket.create_connection((os.environ['RECEIVER'], 8080), timeout=2) as sock:
        case = os.environ['PROFILE']
        sock.sendall(f'GET /hit/{case} HTTP/1.0\r\nHost: receiver\r\n\r\n'.encode())
        response = sock.recv(1024).decode('ascii')
        if '200' not in response.split('\r\n')[0]:
            raise OSError('Resposta inesperada')
        return 'receiver_200'


attempt('direct_network', network)
children = []
try:
    for _ in range(24):
        children.append(subprocess.Popen(['/bin/sleep', '10']))
    records.append({'case': 'pids', 'outcome': 'allowed', 'created': len(children)})
except OSError as error:
    records.append({'case': 'pids', 'outcome': 'denied', 'errno': error.errno,
                    'created': len(children)})
finally:
    for child in children:
        child.terminate()
    for child in children:
        child.wait(timeout=3)
usage = resource.getrusage(resource.RUSAGE_SELF)
print(json.dumps(dict(uid=os.getuid(), gid=os.getgid(), records=records,
    peak_rss_kib=usage.ru_maxrss, cpu_seconds=usage.ru_utime + usage.ru_stime,
    elapsed_seconds=time.monotonic() - start, children_remaining=0,
    cgroup={name: Path('/sys/fs/cgroup', name).read_text().strip()
            for name in ('memory.max', 'pids.max', 'cpu.max', 'memory.peak')})))
