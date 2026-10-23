"""Argumento executável: elegibilidade de uso restrito, nunca certificação."""
from copy import deepcopy
from pathlib import Path
from .common import new_output, read, write, digest, sha, seal, integrity, PROJECT


def decide(case, root, now):
    root=Path(root).resolve()
    reasons=[]
    required={'artifact','owner','scope','claims','exceptions','review','valid_until'}
    if set(case)!=required or case['scope'] not in ('laboratory','production'):
        return {'eligible':False,'reasons':['case_schema']}
    if not case['owner'] or type(now) is not int or type(case['valid_until']) is not int or now>=case['valid_until']:
        reasons.append('owner_or_validity')
    claims=case['claims']
    if not claims or len({c['id'] for c in claims})!=len(claims):
        reasons.append('claims_empty_or_duplicate')
    for claim in claims:
        if (not isinstance(claim.get('id'),str) or not claim['id']
                or type(claim.get('critical')) is not bool):
            reasons.append('claim_schema');continue
        if claim['artifact']!=case['artifact']:
            reasons.append(claim['id']+':candidate_changed')
        if claim['status'] not in ('supported','unknown','refuted'):
            reasons.append(claim['id']+':status'); continue
        if claim['status']=='supported':
            refs=claim.get('evidence',[])
            if not refs: reasons.append(claim['id']+':no_evidence')
            for ref in refs:
                p=(root/ref['path']).resolve()
                if not p.is_relative_to(root) or not p.is_file() or sha(p)!=ref['sha256']:
                    reasons.append(claim['id']+':evidence_changed')
            if not claim.get('warrant') or not claim.get('rebuttal'):
                reasons.append(claim['id']+':argument_missing')
        else:
            ex=next((e for e in case['exceptions'] if e.get('claim')==claim['id']),None)
            valid=bool(ex and ex.get('artifact')==case['artifact'] and ex.get('owner')
                       and ex.get('scope')==case['scope'] and ex.get('mitigation')
                       and type(ex.get('expires')) is int and now<ex['expires'])
            if claim['critical'] or claim['status']=='refuted' or not valid:
                reasons.append(claim['id']+':unsupported')
    review=case['review']
    if case['scope']=='production' and not (
        review.get('independent') is True and review.get('artifact')==case['artifact']
        and review.get('reviewer') and review.get('decision')=='accepted'):
        reasons.append('independent_review_missing')
    return {'eligible':not reasons,'reasons':reasons,
            'decision_kind':'regra didática; não é aceite humano',
            'scope':case['scope'],'artifact':case['artifact']}


def fixture(root):
    candidate=digest({'profile':'laboratory','network':'loopback','policy':'bound-v1'})
    evidence={'test':'resource_and_destination','observation':'forbidden request refused',
              'source':'fixture sintética para exercitar o dossiê; não nova campanha HTTP'}
    write(Path(root)/'evidence.json',evidence)
    claim={'id':'C1','artifact':candidate,'critical':True,'status':'supported',
           'warrant':'Recusa observada no ponto de efeito do caso didático.',
           'rebuttal':'Não sustenta generalização para outro executor ou entrada.',
           'evidence':[{'path':'evidence.json','sha256':sha(Path(root)/'evidence.json')}]}
    return {'artifact':candidate,'owner':'papel fictício: responsável do laboratório',
            'scope':'laboratory','claims':[claim,{'id':'C2','artifact':candidate,
            'critical':False,'status':'unknown','evidence':[]}],
            'exceptions':[{'claim':'C2','artifact':candidate,'owner':'papel fictício: mantenedor',
                'scope':'laboratory','mitigation':'uso isolado; sem dados reais','expires':120}],
            'review':{'independent':False,'reviewer':None,'decision':'pending'},'valid_until':150}


def run(directory):
    out=new_output(directory); base=fixture(out)
    cases={'restricted':deepcopy(base),'production':deepcopy(base),
           'critical_gap':deepcopy(base),'expired_exception':deepcopy(base),
           'changed_candidate':deepcopy(base),'empty':deepcopy(base)}
    cases['production']['scope']='production'
    cases['critical_gap']['claims'][1]['critical']=True
    cases['changed_candidate']['artifact']='another'
    cases['empty']['claims']=[]
    decisions={k:decide(v,out,121 if k=='expired_exception' else 100) for k,v in cases.items()}
    # Referências reais pré-existentes: não convertidas em aprovação da integração nova.
    history=[]
    for relative in ('output/parte7_v01/l28/results.json','output/parte8_v01/l30/report.json',
                     'output/parte8_v01/l32/report.json'):
        file=PROJECT/relative
        if not file.is_file(): raise FileNotFoundError(file)
        history.append({'path':relative,'sha256':sha(file),'reuse':'evidência histórica; candidato distinto'})
    write(out/'cases.json',cases);write(out/'decisions.json',decisions)
    write(out/'historical_evidence.json',history)
    write(out/'review_request.json',{'status':'not_started','reviewer':None,
        'questions':['Tente uma rota não coberta.','Confronte recibos com o argumento.',
                    'Reproduza em ambiente novo.'],'acceptance':'Não atribuída ao autor nem a terceiro.'})
    seal(out);return verify(out)


def verify(directory):
    out=Path(directory);integrity(out)
    cases=read(out/'cases.json');decisions=read(out/'decisions.json')
    assert set(cases)==set(decisions)=={'restricted','production','critical_gap','expired_exception','changed_candidate','empty'}
    for k,v in cases.items():assert decide(v,out,121 if k=='expired_exception' else 100)==decisions[k]
    assert [k for k,v in decisions.items() if v['eligible']]==['restricted']
    assert read(out/'review_request.json')['reviewer'] is None
    for ref in read(out/'historical_evidence.json'):assert sha(PROJECT/ref['path'])==ref['sha256']
    return {'lab':'L33','decisions':6,'eligible_restricted':1,'production_accepted':False}
