"""Runtime sem dependências externas, copiado para uma imagem isolada."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import json
import math
import os
from pathlib import Path
import ssl
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

IDENTITIES = {'aluno-alpha':'alpha','aluno-beta':'beta'}
MODEL = {'coef':[.7,-.4],'intercept':.1}
MODEL_ID = hashlib.sha256(json.dumps(MODEL,sort_keys=True).encode()).hexdigest()


def cache_key(tenant, resource, strict, version='v1'):
    return (tenant,resource,MODEL_ID,version) if strict else (resource,)


def infer(tenant):
    x = [1.,0.] if tenant=='alpha' else [0.,1.]
    score=1/(1+math.exp(-(sum(a*b for a,b in zip(x,MODEL['coef']))+MODEL['intercept'])))
    return {'tenant':tenant,'score':score,'marker':'DADO_'+tenant.upper(),'model':MODEL_ID}


class Service:
    def __init__(self, strict, role='standalone', backend=None, release='v1'):
        self.strict,self.role,self.backend,self.release=strict,role,backend,release
        self.cache={};self.usage={};self.receipts=[]

    def dispatch(self,path,headers,body):
        if path=='/health': return 200,{'release':self.release,'strict':self.strict,'model':MODEL_ID}
        if path.startswith('/admin'):return (403,{'error':'admin_disabled'}) if self.strict else (200,{'admin':True})
        if path not in ('/predict','/batch'):return 404,{'error':'route'}
        if self.role=='backend':
            if self.strict and headers.get('Authorization')!='Bearer servico-local':return 401,{'error':'service_identity'}
            tenant=body.get('tenant','alpha')
            if tenant not in ('alpha','beta'):return 400,{'error':'tenant'}
            response=infer(tenant);response['receipt']=len(self.receipts)+1
            self.receipts.append(response)
            Path('/tmp/receipts.json').write_text(json.dumps(self.receipts))
            return 200,response
        tenant=IDENTITIES.get(headers.get('Authorization','').removeprefix('Bearer '))
        if tenant is None:return 401,{'error':'identity'}
        if path=='/batch':
            # Não implementa batching compartilhado: recusa explicitamente.
            return 400,{'error':'batch_unsupported'}
        if self.strict and self.usage.get(tenant,0)>=5:return 429,{'error':'quota'}
        self.usage[tenant]=self.usage.get(tenant,0)+1
        resource=body.get('resource','case1')
        if resource!='case1':return 404,{'error':'resource'}
        key=cache_key(tenant,resource,self.strict,self.release)
        if key in self.cache:return 200,self.cache[key]|{'cached':True}
        if self.backend:
            request=Request(self.backend+'/predict',data=json.dumps({'tenant':tenant}).encode(),headers={
                'Authorization':'Bearer servico-local','Content-Type':'application/json'})
            try:
                with urlopen(request,timeout=3) as response:result=json.loads(response.read())
            except (HTTPError,OSError):return 502,{'error':'backend'}
        else:
            result=infer(tenant);result['receipt']=len(self.receipts)+1;self.receipts.append(result)
        self.cache[key]=result
        return 200,result|{'cached':False}


def tests(strict):
    s=Service(strict);a={'Authorization':'Bearer aluno-alpha'};b={'Authorization':'Bearer aluno-beta'}
    x=s.dispatch('/predict',a,{'resource':'case1'})
    y=s.dispatch('/predict',b,{'resource':'case1'})
    checks={'functional_success':x[0]==200,'functional_probability':0<x[1]['score']<1,
            'tenant_isolation':y[1]['tenant']=='beta','unauthenticated':s.dispatch('/predict',{}, {})[0]==401,
            'admin_closed':s.dispatch('/admin',a,{})[0]==403}
    return checks


def main():
    config=json.loads(Path('/app/config.json').read_text()) if Path('/app/config.json').exists() else {}
    strict=os.getenv('PROFILE',config.get('profile','strict'))=='strict'
    if len(sys.argv)>1 and sys.argv[1]=='test':
        print(json.dumps(tests(strict)));return
    role=os.getenv('ROLE','standalone')
    s=Service(strict,role,os.getenv('BACKEND'),os.getenv('RELEASE',config.get('release','v1')))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=4096:raise ValueError('size')
                body=json.loads(self.rfile.read(n))
                if not isinstance(body,dict):raise ValueError('object')
                code,result=s.dispatch(self.path,self.headers,body)
            except (ValueError,TypeError,KeyError):code,result=400,{'error':'request'}
            raw=json.dumps(result).encode();self.send_response(code)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
    server=HTTPServer(('0.0.0.0',8443 if role=='gateway' else 8080),Handler)
    if role=='gateway':
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain('/cert/cert.pem','/cert/key.pem')
        server.socket=context.wrap_socket(server.socket,server_side=True)
    server.serve_forever()


if __name__=='__main__':main()
