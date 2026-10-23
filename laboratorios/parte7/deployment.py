"""Rede Docker, TLS e isolamento entre tenants observados em serviços reais."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import time
import uuid
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from .common import new_output, write, read, seal, integrity, sha

BASE='python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2'
DOCKERFILE='FROM '+BASE+'\nWORKDIR /app\nCOPY . /app/\nUSER 10001:10001\nCMD ["python","/app/runtime.py"]\n'
HARDEN=['--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','128m','--tmpfs','/tmp:rw,noexec,nosuid,size=16m']
PROBE='''import json,ssl,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
u,t,b,mode=sys.argv[1:]
c=ssl.create_default_context(cafile='/cert/cert.pem') if mode=='trusted' else ssl.create_default_context()
q=Request(u,data=b.encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+t})
try:
 try:r=urlopen(q,timeout=2,context=c)
 except HTTPError as e:r=e
 with r:print(json.dumps({'status':r.status,'body':json.loads(r.read())}))
except (URLError,OSError) as e:print(json.dumps({'status':0,'error':str(e)}))
'''


def docker(*args,check=True,timeout=90):
    return subprocess.run(['docker',*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace',check=check,timeout=timeout)


def build_image(folder,name,config=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    shutil.copy2(Path(__file__).with_name('runtime.py'),folder/'runtime.py')
    (folder/'Dockerfile').write_text(DOCKERFILE,encoding='utf-8')
    if config:write(folder/'config.json',config)
    result=docker('build','--network','none','-t',name,str(folder))
    return docker('image','inspect',name,'--format','{{.Id}}').stdout.strip(),result.stdout+result.stderr


def certificate(folder):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'gateway')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
          .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('gateway')]),False)
          .sign(key,hashes.SHA256()))
    (folder/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return cert.fingerprint(hashes.SHA256()).hex()


def probe(container,url,token='aluno-alpha',body=None,mode='trusted'):
    return json.loads(docker('exec',container,'python','-c',PROBE,url,token,json.dumps(body or {}),mode).stdout)


def wait_ready(container,url,token='aluno-alpha'):
    for _ in range(30):
        result=probe(container,url,token)
        if result['status']==200:return result
        time.sleep(.2)
    raise RuntimeError('serviço não ficou pronto: '+str(result))


def run(directory):
    out=new_output(directory);prefix='book-l27-'+uuid.uuid4().hex[:10];image=prefix+':local'
    networks=[];containers=[];report={'base':BASE,'docker_version':docker('version','--format','{{.Server.Version}}').stdout.strip(),'profiles':{}}
    with tempfile.TemporaryDirectory(prefix=prefix) as temp:
        temp=Path(temp);cert=temp/'cert';cert.mkdir();report['certificate_fingerprint']=certificate(cert)
        try:
            image_id,log=build_image(temp/'build',image);report['image_id']=image_id
            (out/'build.log').write_text(log,encoding='utf-8')
            for profile in ('weak','strict'):
                front=prefix+'-'+profile+'-front';back=prefix+'-'+profile+'-back'
                for net in (front,back):docker('network','create','--internal',net);networks.append(net)
                backend=prefix+'-'+profile+'-backend';gateway=prefix+'-'+profile+'-gateway';attacker=prefix+'-'+profile+'-client'
                for name,role,net,extra in (
                    (backend,'backend',front if profile=='weak' else back,[]),
                    (gateway,'gateway',front,['--network-alias','gateway','--publish','127.0.0.1::8443',
                                              '-v',str(cert)+':/cert:ro','-e','BACKEND=http://'+backend+':8080']),
                    (attacker,'client',front,['-v',str(cert/'cert.pem')+':/cert/cert.pem:ro'])):
                    args=['run','-d','--name',name,'--network',net,*HARDEN,'-e','ROLE='+role,'-e','PROFILE='+profile,*extra,image_id]
                    if role=='client':args+=['python','-c','import time; time.sleep(300)']
                    docker(*args);containers.append(name)
                docker('network','connect',back,gateway)
                wait_ready(attacker,'https://gateway:8443/health')
                info=json.loads(docker('inspect',backend).stdout)[0]
                ip=info['NetworkSettings']['Networks'][front if profile=='weak' else back]['IPAddress']
                ginfo=json.loads(docker('inspect',gateway).stdout)[0]
                record={'backend_ip':ip,'backend_networks':list(info['NetworkSettings']['Networks']),
                        'gateway_networks':list(ginfo['NetworkSettings']['Networks']),
                        'gateway_ports':ginfo['NetworkSettings']['Ports'],'backend_ports':info['NetworkSettings']['Ports'],
                        'read_only':info['HostConfig']['ReadonlyRootfs'],'user':info['Config']['User'],'checks':{}}
                checks=record['checks']
                checks['direct']=probe(attacker,'http://'+ip+':8080/predict',body={'tenant':'beta'})
                checks['service_without_identity']=probe(gateway,'http://'+ip+':8080/predict',token='invalid')
                checks['service_positive']=probe(gateway,'http://'+ip+':8080/predict',token='servico-local')
                checks['tls_untrusted']=probe(attacker,'https://gateway:8443/health',mode='default')
                gateway_ip=ginfo['NetworkSettings']['Networks'][front]['IPAddress']
                checks['tls_wrong_name']=probe(attacker,'https://'+gateway_ip+':8443/health')
                checks['alpha']=probe(attacker,'https://gateway:8443/predict',body={'tenant':'beta'})
                checks['beta']=probe(attacker,'https://gateway:8443/predict','aluno-beta')
                checks['admin']=probe(attacker,'https://gateway:8443/admin')
                checks['anonymous']=probe(attacker,'https://gateway:8443/predict','invalid')
                checks['batch']=probe(attacker,'https://gateway:8443/batch',body={'tenants':['alpha','beta']})
                checks['quota']=[probe(attacker,'https://gateway:8443/predict') for _ in range(5)]
                checks['beta_after_alpha_quota']=probe(attacker,'https://gateway:8443/predict','aluno-beta')
                receipts=json.loads(docker('exec',backend,'cat','/tmp/receipts.json').stdout)
                record['receipts']=receipts;report['profiles'][profile]=record
            write(out/'results.json',report)
        finally:
            for name in reversed(containers):docker('rm','-f',name,check=False)
            for name in reversed(networks):docker('network','rm',name,check=False)
            docker('image','rm',image,check=False)
            write(out/'cleanup.json',{'containers_remaining':docker('ps','-a','--filter','name='+prefix,'--format','{{.Names}}').stdout.split(),
                  'networks_remaining':docker('network','ls','--filter','name='+prefix,'--format','{{.Name}}').stdout.split()})
    seal(out);return verify(out)


def verify(directory):
    out=Path(directory);integrity(out);r=read(out/'results.json');assert r['base']==BASE
    for profile,record in r['profiles'].items():
        c=record['checks'];strict=profile=='strict'
        assert record['read_only'] and record['user']=='10001:10001' and not record['backend_ports']
        assert all(binding['HostIp']=='127.0.0.1' for bindings in record['gateway_ports'].values() for binding in bindings)
        assert c['direct']['status']==(0 if strict else 200)
        assert c['service_without_identity']['status']==(401 if strict else 200)
        assert c['service_positive']['status']==200
        for key in ('tls_untrusted','tls_wrong_name'):assert c[key]['status']==0 and 'CERTIFICATE_VERIFY_FAILED' in c[key]['error']
        assert c['alpha']['body']['tenant']=='alpha'
        assert c['beta']['body']['tenant']==('beta' if strict else 'alpha')
        assert c['admin']['status']==(403 if strict else 200)
        assert c['anonymous']['status']==401 and c['batch']['status']==400
        assert [q['status'] for q in c['quota']]==([200]*4+[429] if strict else [200]*5)
        assert c['beta_after_alpha_quota']['status']==200
        for key in ('alpha','beta','beta_after_alpha_quota'):
            body=c[key]['body'];assert any(all(body[k]==v for k,v in receipt.items()) for receipt in record['receipts'])
    assert read(out/'cleanup.json')=={'containers_remaining':[],'networks_remaining':[]}
    return {'lab':'L27','verified':True,'deployed_profiles':2,'tls_checks':4,'network_direct_blocked':True,'tenant_cache_separated':True}
