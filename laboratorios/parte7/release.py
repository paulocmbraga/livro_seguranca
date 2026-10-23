"""Pipeline local com build real, gates, smoke HTTP e reversão comprovada."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import zipfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .common import digest, sha, new_output, write, read, seal, integrity
from .deployment import BASE, HARDEN, build_image, docker


def bundle(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,content in sorted(files.items()):
            info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,content)
    return stream.getvalue()


def gate(candidate, evidence, exception=None, now=None):
    if evidence['artifact']!=candidate['artifact'] or evidence['image']!=candidate['image']:
        return False,'evidence_binding'
    expected={'functional_success','functional_probability','tenant_isolation','unauthenticated','admin_closed'}
    checks=evidence['checks']
    if set(checks)!=expected or any(type(v) is not bool for v in checks.values()):
        return False,'incomplete_evidence'
    if not all(checks.values()):return False,'security_or_functional_failure'
    if candidate.get('warning'):
        now=now or datetime.now(timezone.utc)
        if not exception or exception.get('artifact')!=candidate['artifact'] or exception.get('kind')!='documentation':
            return False,'exception_scope'
        expiry=datetime.fromisoformat(exception['expires'])
        if expiry<=now:return False,'exception_expired'
    return True,'eligible'


def http(url,token='aluno-alpha'):
    q=Request(url,data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        try:r=urlopen(q,timeout=2)
        except HTTPError as e:r=e
        with r:return {'status':r.status,'body':json.loads(r.read())}
    except (URLError,OSError):return {'status':0}


def smoke(image,name,override=None):
    args=['run','-d','--name',name,*HARDEN,'--network','bridge','--publish','127.0.0.1::8080']
    if override:args+=['-e','PROFILE='+override]
    try:
        docker(*args,image)
        info=json.loads(docker('inspect',name).stdout)[0]
        binding=info['NetworkSettings']['Ports']['8080/tcp'][0]
        assert binding['HostIp']=='127.0.0.1'
        url='http://127.0.0.1:'+binding['HostPort']
        for _ in range(30):
            health=http(url+'/health')
            if health['status']==200:break
            time.sleep(.2)
        a=http(url+'/predict');b=http(url+'/predict','aluno-beta');anon=http(url+'/predict','invalid')
        ok=health['status']==a['status']==b['status']==200 and b['body']['tenant']=='beta' and anon['status']==401
        return {'image':info['Image'],'health':health,'alpha':a,'beta':b,'anonymous':anon,'pass':ok,'override':override}
    finally:docker('rm','-f',name,check=False)


def run(directory):
    import hashlib
    out=new_output(directory);prefix='book-l28-'+uuid.uuid4().hex[:10];images=[];records={}
    try:
        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            tmp=Path(tmp)
            for name,profile in [('v1','strict'),('v2','strict'),('regression','weak')]:
                image=prefix+'-'+name+':local';images.append(image)
                folder=tmp/name;image_id,log=build_image(folder,image,{'release':name,'profile':profile})
                (out/(name+'_build.log')).write_text(log,encoding='utf-8')
                files={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
                first,second=bundle(files),bundle(dict(reversed(list(files.items()))))
                assert first==second
                artifact=hashlib.sha256(first).hexdigest();(out/(name+'_bundle.zip')).write_bytes(first)
                checks=json.loads(docker('run','--rm','--network','none',*HARDEN,image_id,'python','/app/runtime.py','test').stdout)
                candidate={'artifact':artifact,'image':image_id,'source_files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
                evidence={'artifact':artifact,'image':image_id,'checks':checks}
                accepted,reason=gate(candidate,evidence)
                records[name]={'candidate':candidate,'evidence':evidence,'accepted':accepted,'reason':reason,'bundle_reproduced':True}
            assert records['v1']['accepted'] and records['v2']['accepted'] and not records['regression']['accepted']
            # Troca depois do teste: o gate não deve reutilizar o relatório antigo.
            mismatch=gate(records['regression']['candidate'],records['v2']['evidence'])
            traces=[];pointer=None
            for name,override in [('v1',None),('v2',None),('v2','weak'),('v1',None)]:
                c=records[name]['candidate'];s=smoke(c['image'],prefix+'-runtime',override)
                if s['pass']:pointer={'release':name,**c}
                traces.append({'requested':name,'smoke':s,'active_after_smoke':pointer})
            assert [t['smoke']['pass'] for t in traces]==[True,True,False,True]
            assert pointer['release']=='v1'
            write(out/'active_release.json',pointer)
            write(out/'results.json',{'base':BASE,'candidates':records,'mismatched_evidence':list(mismatch),
                  'deployments':traces,'rollback':pointer,'remote_ci_executed':False,
                  'runtime_fault':'PROFILE=weak injetado pelo controlador depois da promoção; não atravessa o gate como candidato válido.'})
    finally:
        for image in images:docker('image','rm',image,check=False)
        write(out/'cleanup.json',{'containers_remaining':docker('ps','-a','--filter','name='+prefix,'--format','{{.Names}}').stdout.split()})
    seal(out);return verify(out)


def verify(directory):
    import hashlib
    out=Path(directory);integrity(out);r=read(out/'results.json')
    assert r['base']==BASE and r['remote_ci_executed'] is False
    for name,record in r['candidates'].items():
        candidate,evidence=record['candidate'],record['evidence']
        assert sha(out/(name+'_bundle.zip'))==candidate['artifact']
        with zipfile.ZipFile(out/(name+'_bundle.zip')) as z:
            assert {n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}==candidate['source_files']
        assert list(gate(candidate,evidence))==[record['accepted'],record['reason']]
        assert record['bundle_reproduced']
    assert r['candidates']['regression']['evidence']['checks']['functional_success']
    assert not r['candidates']['regression']['evidence']['checks']['tenant_isolation']
    assert r['mismatched_evidence']==[False,'evidence_binding']
    assert [d['smoke']['pass'] for d in r['deployments']]==[True,True,False,True]
    for d in r['deployments']:
        assert d['smoke']['image']==r['candidates'][d['requested']]['candidate']['image']
        assert d['smoke']['health']['body']['release']==d['requested']
        assert d['smoke']['beta']['body']['tenant']==('alpha' if d['smoke']['override']=='weak' else 'beta')
    assert r['rollback']==read(out/'active_release.json')==r['deployments'][-1]['active_after_smoke']
    assert r['rollback']['release']=='v1' and not read(out/'cleanup.json')['containers_remaining']
    return {'lab':'L28','verified':True,'images_built':3,'gate_checks':15,'runtime_smokes':4,
            'regression_blocked':True,'evidence_swap_blocked':True,'rollback_verified':True,'remote_ci':False}
