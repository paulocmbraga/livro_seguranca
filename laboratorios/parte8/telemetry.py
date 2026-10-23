"""Assinatura real, entrega perturbada pelo harness e reconciliação de efeitos."""
from datetime import datetime, timezone
from pathlib import Path
import copy
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from .common import canonical, digest, read, write, new_output, seal, integrity
from .runtime import service, call, effects
from .campaign import candidates

FIELDS={'request_id','kind','decision'}


def minimize(value):
    result={k:value[k] for k in FIELDS if k in value}
    if set(result)!=FIELDS or result['kind'] not in ('decision','effect'):
        raise ValueError('event schema')
    if not isinstance(result['request_id'],str) or not result['request_id'].replace('-','').isalnum():
        raise ValueError('request id')
    if result['decision'] not in ('allow','deny','committed'):
        raise ValueError('decision')
    return result


class Producer:
    def __init__(self,name):
        self.name=name;self.key=Ed25519PrivateKey.generate();self.events=[]

    @property
    def public(self):
        return self.key.public_key().public_bytes_raw().hex()

    def emit(self,value):
        body={'producer':self.name,'seq':len(self.events)+1,
              'previous':digest(self.events[-1]) if self.events else '0'*64,
              'utc':datetime.now(timezone.utc).isoformat(),'mono_ns':time.monotonic_ns(),
              **minimize(value)}
        event={'body':body,'signature':self.key.sign(canonical(body)).hex()}
        self.events.append(event);return event

    def anchor(self):
        body={'producer':self.name,'count':len(self.events),
              'head':digest(self.events[-1]) if self.events else '0'*64}
        return {'body':body,'signature':self.key.sign(canonical(body)).hex()}


def authentic(event,public):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
            bytes.fromhex(event['signature']),canonical(event['body']))
        return True
    except (InvalidSignature,ValueError,KeyError,TypeError):
        return False


def reconcile(events,anchors,public_keys,receipts):
    valid={};invalid=0;duplicates=0;forks=[]
    for e in events:
        b=e.get('body',{});producer=b.get('producer')
        if producer not in public_keys or not authentic(e,public_keys[producer]):
            invalid+=1;continue
        key=(producer,b['seq'])
        if key in valid:
            if valid[key]==e:duplicates+=1
            else:forks.append(list(key))
        else:valid[key]=e
    gaps={};chain_errors=[];anchor_errors=[]
    for producer,anchor in anchors.items():
        if (producer not in public_keys or not authentic(anchor,public_keys[producer])
            or anchor.get('body',{}).get('producer') != producer
            or type(anchor.get('body',{}).get('count')) is not int
            or anchor['body']['count'] < 0):
            anchor_errors.append(producer);continue
        a=anchor['body'];n=a['count']
        gaps[producer]=[i for i in range(1,n+1) if (producer,i) not in valid]
        own={seq:e for (p,seq),e in valid.items() if p==producer}
        if any(seq<1 or seq>n for seq in own):anchor_errors.append(producer)
        if n in own and digest(own[n])!=a['head']:anchor_errors.append(producer)
        for seq,event in own.items():
            expected='0'*64 if seq==1 else digest(own[seq-1]) if seq-1 in own else None
            if expected is not None and event['body']['previous']!=expected:
                chain_errors.append([producer,seq])
    bodies=[e['body'] for e in valid.values()]
    observed_effects={b['request_id'] for b in bodies if b['kind']=='effect'}
    decisions={b['request_id']:b['decision'] for b in bodies if b['kind']=='decision'}
    actual={r['id'] for r in receipts}
    unauthorized=[r['id'] for r in receipts if r['owner']!=r['actor'] or r['destination']!='internal']
    return {'invalid_signatures':invalid,'duplicates':duplicates,'forks':forks,
            'gaps':gaps,'chain_errors':chain_errors,'anchor_errors':anchor_errors,
            'missing_effect_events':sorted(actual-observed_effects),
            'unsupported_effect_claims':sorted(observed_effects-actual),
            'missing_decisions':sorted(actual-set(decisions)),
            'contradictory_denials':sorted(i for i in actual if decisions.get(i)=='deny'),
            'unauthorized_receipts':sorted(unauthorized),
            'alert':bool(unauthorized or actual-observed_effects or observed_effects-actual
                         or actual-set(decisions) or any(decisions.get(i)=='deny' for i in actual)
                         or invalid or forks or chain_errors or anchor_errors
                         or any(gaps.values()))}


def run(path):
    out=new_output(path);controller=Producer('controller');destination=Producer('destination')
    requests=[dict(p,id=f'r{i}') for i,p in enumerate(candidates())]
    requests += [{'id':f'r{i+5}','owner':'alpha','destination':'internal','text':t}
                 for i,t in enumerate(('rotina','auditar segredo','exportar inventário'))]
    with service(out/'destination.sqlite','filter') as url:
        for p in requests:
            result=call(url,p)
            controller.emit({'request_id':p['id'],'kind':'decision',
                             'decision':'allow' if result['status']==200 else 'deny',
                             'raw_prompt':'TELEMETRY_CANARY_31','authorization':'demo-alpha'})
    receipts=effects(out/'destination.sqlite')
    for r in receipts:
        destination.emit({'request_id':r['id'],'kind':'effect','decision':'committed'})
    all_events=controller.events+destination.events
    anchors={p.name:p.anchor() for p in (controller,destination)}
    keys={p.name:p.public for p in (controller,destination)}
    # Omissão no meio do controlador e na cauda do destino; atraso por lotes.
    omitted=[controller.events[1],destination.events[-1]]
    delivered=[e for e in reversed(all_events) if e not in omitted]+[controller.events[0]]
    tampered=copy.deepcopy(controller.events[0]);tampered['body']['decision']='allow'
    forged=Producer('destination').emit({'request_id':'false1','kind':'effect','decision':'committed'})
    delivered += [tampered,forged]
    # Alegação falsa assinada pelo produtor autorizado: assinatura continua válida.
    false_claim=destination.emit({'request_id':'false2','kind':'effect','decision':'committed'})
    final_events=all_events+[false_claim]
    final_anchors={'controller':controller.anchor(),'destination':destination.anchor()}
    damaged=reconcile(delivered,anchors,keys,receipts)
    restored=reconcile(all_events,anchors,keys,receipts)
    signed_false=reconcile(final_events,final_anchors,keys,receipts)
    assert 'TELEMETRY_CANARY_31' not in canonical(all_events).decode()
    report={'damaged':damaged,'restored':restored,'signed_false':signed_false,
            'events_original':len(all_events),'http_calls':8,
            'delivery':'ordem/atraso/perda injetados em lotes locais, sem broker distribuído',
            'time_source':'UTC do host + monotonic_ns do mesmo processo; sem NTP qualificado',
            'custody':'chaves privadas efêmeras não exportadas; âncoras no mesmo host confiável'}
    for name,value in [('events',all_events),('delivered',delivered),('anchors',anchors),
                       ('public_keys',keys),('receipts',receipts),('false_events',final_events),
                       ('false_anchors',final_anchors),('report',report)]:write(out/(name+'.json'),value)
    seal(out);return verify(out)


def verify(path):
    out=Path(path);integrity(out);r=read(out/'report.json');keys=read(out/'public_keys.json')
    receipts=effects(out/'destination.sqlite');assert receipts==read(out/'receipts.json')
    for label,event_file,anchor_file in [('damaged','delivered','anchors'),('restored','events','anchors'),('signed_false','false_events','false_anchors')]:
        assert r[label]==reconcile(read(out/(event_file+'.json')),read(out/(anchor_file+'.json')),keys,receipts)
    assert r['damaged']['invalid_signatures']==2 and r['damaged']['duplicates']==1
    assert r['damaged']['gaps']=={'controller':[2],'destination':[5]}
    assert not any(r['restored']['gaps'].values())
    assert r['signed_false']['unsupported_effect_claims']==['false2']
    assert r['signed_false']['invalid_signatures']==0
    return r
