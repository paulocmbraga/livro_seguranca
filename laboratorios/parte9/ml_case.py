"""Treino, ataque e regressão de cache no mesmo serviço de ML implantado."""
from copy import deepcopy
from pathlib import Path
import json
import math
import shutil
import tempfile
import time
import uuid

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from diffprivlib.models import LogisticRegression as DPLogisticRegression
from diffprivlib.accountant import BudgetAccountant

from laboratorios.parte6.pipeline import Store, validate_training
from laboratorios.parte6.poisoning import data, change
from laboratorios.parte6.common import linear_export, linear_scores, matrix, accuracy
from laboratorios.parte7.deployment import BASE, HARDEN, docker
from laboratorios.parte7.release import bundle
from .common import new_output, write, read, digest, sha, seal, integrity, serve, call, database


def release_gate(candidate,evidence):
    required={'utility','input_contract','identity','tenant_cache','quota','lineage'}
    if evidence.get('candidate')!=digest(candidate):return False,'candidate_binding'
    checks=evidence.get('checks',{})
    if set(checks)!=required or any(type(v) is not bool for v in checks.values()):return False,'incomplete'
    return (True,'eligible_laboratory') if all(checks.values()) else (False,'failed_property')


def prepare_rows(seed,split,n):
    rows=data(seed,split,n)
    for r in rows:
        r['x']=np.clip(r['x'],-1,1).tolist()
        r.update(split=split,group=r['id'],training_allowed=split=='train')
    return rows


def train_case(out):
    train=prepare_rows(3401,'train',400)
    holdout=prepare_rows(3491,'test',120)
    rows=train+holdout
    manifest={r['id']:{'digest':digest(r),'split':r['split'],
               'training_allowed':r['training_allowed'],'group':r['group']} for r in rows}
    store=Store(out/'store.sqlite',rows)
    with serve(store.dispatch) as url:
        status,response=call(url+'/read',store.tokens['trainer'],{'ids':[r['id'] for r in train]})
        assert status==200;train=response['rows'];validate_training(train,manifest)
        denied,_=call(url+'/read',store.tokens['trainer'],{'ids':[r['id'] for r in holdout]})
        assert denied==403
        x,y=matrix(train)
        plain=linear_export(LogisticRegression(C=1,max_iter=1000,random_state=34).fit(x,y))
        accountant=BudgetAccountant(epsilon=8,delta=0)
        dp=linear_export(DPLogisticRegression(epsilon=8,data_norm=math.sqrt(6),C=1,
                max_iter=1000,random_state=34,accountant=accountant).fit(x,y))
        poisoned,changed=change(train,32,'adaptive',34)
        try:validate_training(poisoned,manifest);raise AssertionError('poison accepted')
        except ValueError as e:poison_refusal=str(e)
        px,py=matrix(poisoned)
        compromised=linear_export(LogisticRegression(C=1,max_iter=1000,random_state=34).fit(px,py))
        # Adaptação real sem DP aos dados privados: não herda a garantia do ajuste anterior.
        w=np.asarray(dp['coef']);b=dp['intercept']
        for _ in range(100):
            error=1/(1+np.exp(-(x@w+b)))-y
            w-=.1*x.T@error/len(y);b-=.1*float(error.mean())
        adapted={'kind':'logistic','coef':w.tolist(),'intercept':b,'classes':[0,1]}
        models={'plain':plain,'dp':dp,'poisoned':compromised,'adapted_private':adapted}
        write(out/'models.json',models)
        write(out/'freeze.json',{'models':{k:digest(v) for k,v in models.items()},
            'training_ids':[r['id'] for r in train],'threshold_utility':.70,
            'epsilon':8,'seed':34,'steps_nonprivate_adaptation':100,
            'test_used_for_selection':False,'privacy_lineage_adapted_valid':False})
        status,response=call(url+'/read',store.tokens['evaluator'],{'ids':[r['id'] for r in holdout]})
        assert status==200;holdout=response['rows']
    tx,ty=matrix(holdout)
    predictions={k:linear_scores(v,tx).tolist() for k,v in models.items()}
    metrics={k:accuracy(ty,v) for k,v in predictions.items()}
    perturb=np.clip(tx-.08*(2*ty-1)[:,None]*np.sign(dp['coef']),-1,1)
    perturbed=linear_scores(dp,perturb)
    correct=(np.asarray(predictions['dp'])>=.5)==ty
    evasion={'budget_linf':.08,'eligible':int(correct.sum()),
             'flips':int(np.sum(correct & ((perturbed>=.5)!=ty))),
             'predictions':perturbed.tolist(),'x':perturb.tolist()}
    target=np.where(ty==0)[0];trigger=tx[target].copy();trigger[:,5]=1
    clean_target=linear_scores(compromised,tx[target]);triggered=linear_scores(compromised,trigger)
    poison={'changed_ids':changed,'provenance_refusal':poison_refusal,
            'eligible':int(np.sum(clean_target<.5)),
            'new_flips':int(np.sum((clean_target<.5)&(triggered>=.5)))}
    write(out/'data.json',{'train':train,'test':holdout,'poisoned':poisoned})
    write(out/'data_manifest.json',manifest)
    write(out/'training.json',{'metrics':metrics,'predictions':predictions,'evasion':evasion,
        'poison':poison,'accountant':list(accountant.total()),'trainer_test_status':denied,
        'privacy_limit':'Synthetic data and public deterministic seed: demonstration, not a private release.'})
    return models,metrics


def exercise_image(image,name,queries):
    try:
        docker('run','-d','--name',name,*HARDEN,'--cpus','1','--network','bridge',
               '--publish','127.0.0.1::8080',image)
        info=json.loads(docker('inspect',name).stdout)[0]
        binding=info['NetworkSettings']['Ports']['8080/tcp'][0];assert binding['HostIp']=='127.0.0.1'
        url='http://127.0.0.1:'+binding['HostPort']
        for _ in range(30):
            try:
                if call(url+'/health','invalid',{})[0]==200:break
            except OSError:time.sleep(.2)
        observations=[]
        def ask(label,token,x):
            s,b=call(url+'/predict',token,{'x':x})
            observations.append({'case':label,'status':s,'body':b,'x':x});return s,b
        ask('anonymous','invalid',[0]*6)
        ask('invalid_features','synthetic-alpha',[False]*6)
        ask('alpha','synthetic-alpha',[.2]*6)
        ask('beta_same_input','synthetic-beta',[.2]*6)
        for i,x in enumerate(queries):ask('extract_'+str(i),'synthetic-alpha',x)
        receipts=json.loads(docker('exec',name,'cat','/tmp/receipts.json').stdout)
        return {'image':info['Image'],'config':{k:info['HostConfig'][k] for k in
                ('ReadonlyRootfs','CapDrop','SecurityOpt','Memory','PidsLimit','NetworkMode')},
                'observations':observations,'receipts':receipts,'user':info['Config']['User']}
    finally:docker('rm','-f',name,check=False)


def run(directory):
    out=new_output(directory);models,metrics=train_case(out)
    prefix='book-l34-'+uuid.uuid4().hex[:10];images=[];profiles={}
    rng=np.random.default_rng(3434);queries=rng.uniform(-1,1,(12,6)).tolist()
    try:
        with tempfile.TemporaryDirectory(prefix=prefix) as folder:
            for profile in ('weak','strict'):
                build=Path(folder)/profile;build.mkdir()
                shutil.copy2(Path(__file__).with_name('ml_runtime.py'),build/'runtime.py')
                write(build/'model.json',models['dp']);write(build/'config.json',{'strict':profile=='strict'})
                (build/'Dockerfile').write_bytes(('FROM '+BASE+'\nWORKDIR /app\nCOPY . /app/\nUSER 10001:10001\nCMD ["python","/app/runtime.py"]\n').encode())
                files={p.name:p.read_bytes() for p in build.iterdir()}
                package=bundle(files);assert package==bundle(dict(reversed(list(files.items()))))
                (out/(profile+'_bundle.zip')).write_bytes(package)
                image=prefix+'-'+profile+':local';images.append(image)
                result=docker('build','--network','none','--pull=false','-t',image,build)
                (out/(profile+'_build.log')).write_bytes((result.stdout+result.stderr).encode())
                image_id=docker('image','inspect',image,'--format','{{.Id}}').stdout.strip()
                record=exercise_image(image_id,prefix+'-serving',queries)
                obs={r['case']:r for r in record['observations']}
                candidate={'bundle':sha(out/(profile+'_bundle.zip')),'image':image_id,
                           'model':digest(models['dp']),'config':profile,'privacy_lineage':'dp_only'}
                checks={'utility':metrics['dp']['accuracy']>=.70,
                    'input_contract':obs['invalid_features']['status']==400,
                    'identity':obs['anonymous']['status']==401,
                    'tenant_cache':obs['beta_same_input']['body'].get('tenant')=='beta',
                    'quota':sum(r['status']==429 for r in record['observations'])==5,
                    'lineage':True}
                evidence={'candidate':digest(candidate),'checks':checks}
                extracted=[r for r in record['observations'] if r['case'].startswith('extract_') and r['status']==200]
                surrogate=DecisionTreeClassifier(max_depth=3,random_state=34).fit(
                    [r['x'] for r in extracted],[int(r['body']['score']>=.5) for r in extracted])
                tx,_=matrix(read(out/'data.json')['test'])
                fidelity=float(np.mean(surrogate.predict(tx)==(linear_scores(models['dp'],tx)>=.5)))
                profiles[profile]={'candidate':candidate,'evidence':evidence,'gate':list(release_gate(candidate,evidence)),
                   'runtime':record,'extraction':{'queries':12,'answered':len(extracted),
                     'surrogate_fidelity_n':len(tx),'surrogate_fidelity':fidelity}}
                write(out/(profile+'_evidence.json'),profiles[profile])
        altered=deepcopy(profiles['strict']['candidate']);altered['privacy_lineage']='nonprivate_adaptation'
        stale=release_gate(altered,profiles['strict']['evidence'])
        write(out/'results.json',{'profiles':profiles,'stale_evidence':list(stale),'base':BASE,
            'docker_version':docker('version','--format','{{.Server.Version}}').stdout.strip(),
            'campaign':'same-host synthetic; labels withheld from trainer API, author knows generator',
            'production_release':False,'independent_review':'pending'})
    finally:
        for image in images:docker('image','rm',image,check=False)
        write(out/'cleanup.json',{'containers_remaining':docker('ps','-a','--filter','name='+prefix,'--format','{{.Names}}').stdout.split()})
    seal(out);return verify(out)


def verify(directory):
    out=Path(directory);integrity(out);r=read(out/'results.json');train=read(out/'training.json')
    models=read(out/'models.json');data_=read(out/'data.json');x,y=matrix(data_['test'])
    for key,model in models.items():
        assert np.allclose(linear_scores(model,x),train['predictions'][key])
        assert accuracy(y,train['predictions'][key])==train['metrics'][key]
    assert train['trainer_test_status']==403 and train['accountant']==[8.0,0.0]
    for key,record in r['profiles'].items():
        assert sha(out/(key+'_bundle.zip'))==record['candidate']['bundle']
        assert list(release_gate(record['candidate'],record['evidence']))==record['gate']
        obs=record['runtime']['observations'];assert len(obs)==16
        assert sum(row['status']==429 for row in obs)==5
        for row in obs:
            if row['status']==200:
                assert math.isclose(row['body']['score'],float(linear_scores(models['dp'],[row['x']])[0]),abs_tol=1e-12)
        beta=next(v for v in obs if v['case']=='beta_same_input')
        assert beta['body']['tenant']==('alpha' if key=='weak' else 'beta')
        assert len(record['runtime']['receipts'])==(8 if key=='weak' else 9)
    assert not r['profiles']['weak']['gate'][0]
    assert r['stale_evidence']==[False,'candidate_binding']
    assert not read(out/'cleanup.json')['containers_remaining']
    return {'lab':'L34','training_fits':3,'adaptation_steps':100,'http_predictions':32,
            'profiles':{k:v['gate'] for k,v in r['profiles'].items()},'metrics':train['metrics']}
