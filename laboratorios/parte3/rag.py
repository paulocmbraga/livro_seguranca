"""Extensão aditiva do piloto: corpus congelado antes da primeira geração."""
import json
from pathlib import Path
from unittest.mock import patch

from laboratorios.l09 import campaign
from .common import PROJECT,new_output,write,seal,integrity,sha
from .runtime import model


def run(directory,cache,config,closed_resources=False):
    out=new_output(directory)
    corpus=json.loads((PROJECT/'materiais/parte3/rag_reserva.json').read_text(encoding='utf-8'))
    # A substituição limita-se ao processo da campanha, sem editar fontes históricas.
    with model(cache,config,out/'runtime',max_calls=8,closed_resources=closed_resources) as adapter:
        with patch.object(campaign,'make_corpus',return_value=corpus):
            report=campaign.run(out/'campaign',split='eval',adapter=adapter)
    report['real_inference']=True
    report['extension']='L09-ParteIII-reserva-autoral-1.0'
    report['limitations']=['8 casos novos congelados antes da primeira inferência; conhecidos pelo autor.',
                          'Q4/Q8 são quantizações da mesma família, não diversidade de modelos.',
                          'Propostas reais; autorização e destino preservados do piloto.']
    write(out/'campaign/results.json',report)
    nested=json.loads((out/'campaign/manifest.json').read_text(encoding='utf-8'))
    nested['artifacts_sha256']['results.json']=sha(out/'campaign/results.json')
    write(out/'campaign/manifest.json',nested)
    write(out/'results.json',{'lab':'L09','config':config,'cases':8,'trajectories':32,
                            'summary':report['summary'],'calls':adapter.calls,'closed_resources':closed_resources})
    seal(out)
    return verify(out)


def verify(directory):
    from laboratorios.l09.services import records
    out=Path(directory); integrity(out)
    campaign.verify(out/'campaign')
    r=json.loads((out/'campaign/results.json').read_text(encoding='utf-8'))
    corpus=json.loads((out/'campaign/corpus.json').read_text(encoding='utf-8'))
    events=records(out/'campaign/domain.sqlite','events')
    receipts=records(out/'campaign/destination.sqlite','receipts')
    expected={f"{c['id']}_{v}_r1" for c in corpus['cases'] for v in 'ABCD'}
    assert len(r['results'])==len(expected)==32
    assert {row['trace_id'] for row in r['results']}==expected
    summary=campaign.summarize([campaign.observe(dict(row),events,receipts) for row in r['results']])
    assert summary==r['summary']
    ledger=json.loads((out/'runtime/inference_ledger.json').read_text(encoding='utf-8'))
    assert len(ledger)==r['inference_calls']==8
    assert all(row['real_inference'] for row in ledger)
    top=json.loads((out/'results.json').read_text(encoding='utf-8'))
    assert top['summary']==summary and top['trajectories']==32
    return {'lab':'L09','trajectories':32,'calls':8,'errors':sum(s['errors'] for s in summary.values()),'summary':summary}
