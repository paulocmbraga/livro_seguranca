"""Inferência CPU real, limitada, com llama.cpp e a bancada HTTP do L09."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import psutil

from laboratorios.l09 import campaign
from laboratorios.l09.core import Action, digest
from laboratorios.l09.llm import messages, SCHEMA, InferenceError
from .common import PROJECT, sha, write, seal


def http(url, payload=None, timeout=120):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def decode(response):
    try:
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('Geração truncada')
        return Action.parse(json.loads(choice['message']['content']))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise InferenceError('Resposta incompleta ou fora do contrato', response) from exc


class Adapter:
    name = 'llama_cpp_cpu'

    def __init__(self, url, config, max_calls=20, max_seconds=900):
        if type(max_calls) is not int or not 1 <= max_calls <= 40:
            raise ValueError('max_calls deve estar entre 1 e 40')
        self.url, self.config = url, config
        self.max_calls, self.max_seconds = max_calls, max_seconds
        self.started = time.monotonic()
        self.calls, self.cache, self.ledger = 0, {}, []
        self.metadata = {'config': config, 'temperature': 0, 'seed': 17,
                         'max_tokens': 128, 'max_calls': max_calls,
                         'max_seconds': max_seconds, 'json_schema': SCHEMA}

    def propose(self, query, context, tenant, repeat):
        prompt = messages(query, context, tenant)
        key = digest({'messages': prompt, 'repeat': repeat, 'config': self.config})
        if key in self.cache:
            action, evidence, error = self.cache[key]
            evidence = {**evidence, 'cache_hit': True}
            if error:
                raise InferenceError(error, evidence)
            return action, evidence
        elapsed = time.monotonic() - self.started
        if self.calls >= self.max_calls or elapsed >= self.max_seconds:
            raise RuntimeError('budget_exhausted')
        self.calls += 1
        started = time.monotonic()
        payload = {'model': self.config, 'messages': prompt, 'temperature': 0,
                   'seed': 17, 'max_tokens': 128, 'stream': False,
                   'response_format': {'type': 'json_schema', 'json_schema': {
                       'name': 'action', 'strict': True, 'schema': SCHEMA}}}
        evidence = {'adapter': self.name, 'real_inference': True, 'cache_hit': False,
                    'call_number': self.calls, 'prompt_sha256': key, 'request': payload}
        action, error = None, None
        try:
            response = http(self.url + '/v1/chat/completions', payload,
                            timeout=max(1, min(120, self.max_seconds - elapsed)))
            evidence['response'] = response
            action = decode(response)
        except (HTTPError, URLError, TimeoutError, InferenceError) as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        evidence['elapsed_seconds'] = round(time.monotonic() - started, 4)
        self.ledger.append({**evidence, 'error': error})
        self.cache[key] = action, evidence, error
        if error:
            raise InferenceError(error, evidence)
        return action, evidence


def run(directory, cache, config):
    out, cache = Path(directory).resolve(), Path(cache).resolve()
    if out.exists():
        raise FileExistsError('Captura já existe; use outro diretório')
    lock = json.loads((PROJECT / 'materiais/m1/artefatos.lock.json').read_text())
    item = next(a for a in lock['artifacts'] if a['id'] == config)
    runtime = next(a for a in lock['artifacts'] if a['id'] == 'llama_cpp_cpu')
    for artifact in (item, runtime):
        if sha(cache / artifact['filename']) != artifact['sha256']:
            raise ValueError('Artefato não corresponde ao lock')
    exe = cache / 'runtime_b11669/llama-server.exe'
    # Reserva efêmera; uma corrida de porta causa falha explícita, nunca troca silenciosa.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    args = [str(exe), '-m', str(cache / item['filename']), '--host', '127.0.0.1',
            '--port', str(port), '-t', '4', '-tb', '4', '-c', '2048', '-np', '1',
            '-ngl', '0', '--no-webui', '--alias', config]
    log = cache / f'{config}_{time.time_ns()}.log'
    stats, stop = [], threading.Event()
    started = time.monotonic()
    with log.open('wb') as stream:
        proc = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def monitor():
            monitored = psutil.Process(proc.pid)
            while not stop.wait(.25):
                try:
                    stats.append({'elapsed': round(time.monotonic()-started, 3),
                                  'rss': monitored.memory_info().rss,
                                  'cpu_seconds': sum(monitored.cpu_times()[:2]),
                                  'available_ram': psutil.virtual_memory().available})
                except psutil.Error:
                    return
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        try:
            url = f'http://127.0.0.1:{port}'
            while True:
                if proc.poll() is not None or time.monotonic()-started > 90:
                    raise RuntimeError('llama-server não iniciou; consulte ' + str(log))
                try:
                    if http(url + '/health', timeout=1).get('status') == 'ok':
                        break
                except (OSError, ValueError):
                    time.sleep(.25)
            adapter = Adapter(url, config)
            report = campaign.run(out, split='dev', adapter=adapter)
            report.update(version='M1-L09-1.0', real_inference=True,
                          inference_config=item,
                          limitations=[
                              '20 casos autorais de desenvolvimento; não é holdout independente.',
                              'Q4 e Q8 são duas quantizações da mesma família e dos mesmos pesos.',
                              'Busca lexical e prompt do piloto preservados; não mede embeddings.',
                              'Uma geração por caso, reutilizada entre variantes; não são 80 amostras de LLM.',
                              'JSON guiado restringe sintaxe; não concede autorização.',
                              'HTTP loopback e mesmo usuário; sem TLS, OAuth ou sandbox nesta bancada RAG.'])
            write(out / 'results.json', report)
            write(out / 'inference_ledger.json', adapter.ledger)
        finally:
            stop.set()
            worker.join(2)
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
    write(out / 'resources.json', {
        'model': item, 'runtime': runtime, 'executable_sha256': sha(exe),
        'arguments': args[3:], 'elapsed_seconds': round(time.monotonic()-started, 3),
        'process_rss_peak_bytes': max(s['rss'] for s in stats),
        'cpu_seconds': max(s['cpu_seconds'] for s in stats),
        'available_ram_min_bytes': min(s['available_ram'] for s in stats),
        'sampling_seconds': .25, 'samples': stats,
        'measurement_limit': 'RSS amostrada do servidor, não memória total da bancada nem pico contínuo.'})
    (out / 'llama_server.log').write_bytes(log.read_bytes())
    seal(out)
    verified = campaign.verify(out)
    print(json.dumps({'config': config, 'calls': adapter.calls, 'verification': verified}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--config', choices=['q4_k_m', 'q8_0'], required=True)
    args = parser.parse_args()
    run(args.out, args.cache, args.config)
