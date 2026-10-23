"""Mede quatro execuções sequenciais próprias; não é benchmark de produção."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil

PROJECT = Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.out).resolve();root.mkdir(parents=True,exist_ok=False)
    rows=[]
    for lab in ('L29','L30','L31','L32'):
        command=[sys.executable,'-m','laboratorios.parte8','run',lab,'--out',str(root/lab.lower())]
        started=time.perf_counter();peak=0;samples=0
        with (root/(lab.lower()+'.log')).open('wb') as log:
            process=subprocess.Popen(command,cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT)
            try:
                owner=psutil.Process(process.pid)
                while process.poll() is None:
                    if time.perf_counter()-started>900:
                        raise TimeoutError(lab+' exceeded qualification budget')
                    rss=0
                    try: children=owner.children(recursive=True)+[owner]
                    except psutil.NoSuchProcess:children=[]
                    for child in children:
                        try:rss+=child.memory_info().rss
                        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                    peak=max(peak,rss);samples+=1;time.sleep(.1)
                if process.returncode:raise RuntimeError(lab+' failed; preserve log')
            finally:
                if process.poll() is None:
                    try:
                        for child in owner.children(recursive=True):child.terminate()
                    except psutil.NoSuchProcess:pass
                    process.terminate();process.wait(timeout=10)
        rows.append({'lab':lab,'seconds':time.perf_counter()-started,
                     'sampled_peak_tree_rss_mib':peak/1024**2,'samples':samples,'returncode':process.returncode})
    report={'runs':rows,'sample_interval_seconds':.1,'sequential_same_host':True,
            'limits':'Soma RSS dos processos próprios vivos; pode contar páginas compartilhadas mais de uma vez e perder picos. Inclui imports e encerramento. Não inclui instalação/download nem RAM total do host. HTTP, SQLite e subprocesso locais. Sem modelo treinado nem Docker nesta parte. Sem API paga ou LLM pré-treinado; instalação e download não incluídos.'}
    (root/'resources.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
