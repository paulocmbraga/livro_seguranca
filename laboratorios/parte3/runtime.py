"""Servidor de inferência local limitado; reutiliza artefatos M1 fixados."""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from unittest.mock import patch
import copy

import psutil

from laboratorios.m1.inference import http, Adapter
from laboratorios.m1 import inference as legacy_inference
from .common import PROJECT, sha, write


@contextmanager
def model(cache, config, evidence, max_calls=20, closed_resources=False):
    cache, evidence = Path(cache).resolve(), Path(evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    lock=json.loads((PROJECT/'materiais/m1/artefatos.lock.json').read_text(encoding='utf-8'))
    model_info=next(a for a in lock['artifacts'] if a['id']==config)
    runtime_info=next(a for a in lock['artifacts'] if a['id']=='llama_cpp_cpu')
    for item in (model_info,runtime_info):
        if sha(cache/item['filename'])!=item['sha256']:
            raise ValueError('Modelo/runtime divergente do lock M1')
    executable=cache/'runtime_b11669/llama-server.exe'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    command=[str(executable),'-m',str(cache/model_info['filename']),'--host','127.0.0.1',
             '--port',str(port),'-t','4','-tb','4','-c','2048','-np','1','-ngl','0',
             '--no-webui','--alias',config]
    started=time.monotonic(); samples=[]; stop=threading.Event()
    with (evidence/'server.log').open('wb') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def monitor():
            p=psutil.Process(process.pid)
            while not stop.wait(.25):
                try: samples.append({'seconds':round(time.monotonic()-started,3),
                                     'rss':p.memory_info().rss,'cpu_seconds':sum(p.cpu_times()[:2])})
                except psutil.Error: return
        thread=threading.Thread(target=monitor,daemon=True); thread.start()
        adapter=None
        try:
            url=f'http://127.0.0.1:{port}'
            while True:
                if process.poll() is not None or time.monotonic()-started>90:
                    raise RuntimeError('Servidor local não iniciou')
                try:
                    if http(url+'/health',timeout=1).get('status')=='ok': break
                except (OSError,ValueError): time.sleep(.25)
            schema=copy.deepcopy(legacy_inference.SCHEMA)
            if closed_resources:
                schema['properties']['resource']['enum']=['alpha_contract','beta_contract']
            with patch.object(legacy_inference,'SCHEMA',schema):
                adapter=Adapter(url,config,max_calls=max_calls,max_seconds=600)
                adapter.metadata['closed_resources']=closed_resources
                yield adapter
        finally:
            stop.set(); thread.join(2); process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(5)
            write(evidence/'resources.json',{'config':model_info,'runtime':runtime_info,
                  'executable_sha256':sha(executable),'arguments':command[3:],
                  'elapsed_seconds':round(time.monotonic()-started,3),'samples':samples,
                  'rss_peak_bytes':max((s['rss'] for s in samples),default=0),
                  'process_ended':process.poll() is not None,
                  'calls':adapter.calls if adapter else 0})
            if adapter: write(evidence/'inference_ledger.json',adapter.ledger)
