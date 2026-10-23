"""Serving do artefato treinado, executado no contêiner Linux sem bibliotecas ML."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import json
import math
from pathlib import Path


def score(model,x):
    z=sum(a*b for a,b in zip(model['coef'],x))+model['intercept']
    return 1/(1+math.exp(-max(-700,min(700,z))))


class Service:
    def __init__(self,model,strict=True,limit=8):
        self.model,self.strict,self.limit=model,strict,limit
        self.model_hash=hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.cache={};self.usage={};self.receipts=[]

    def dispatch(self,path,headers,body):
        if path=='/health':return 200,{'model':self.model_hash,'strict':self.strict}
        token=headers.get('Authorization','')
        tenant={'Bearer synthetic-alpha':'alpha','Bearer synthetic-beta':'beta'}.get(token)
        if tenant is None:return 401,{'error':'identity'}
        if path!='/predict':return 404,{'error':'route'}
        x=body.get('x')
        if not isinstance(x,list) or len(x)!=len(self.model['coef']) or any(
            type(v) not in (float,int) or not math.isfinite(v) or abs(v)>1 for v in x):
            return 400,{'error':'features'}
        if self.usage.get(tenant,0)>=self.limit:return 429,{'error':'quota'}
        self.usage[tenant]=self.usage.get(tenant,0)+1
        key=(tenant,self.model_hash,tuple(x)) if self.strict else tuple(x)
        if key in self.cache:return 200,{**self.cache[key],'cached':True}
        result={'tenant':tenant,'score':score(self.model,x),'model':self.model_hash,
                'marker':'SYNTHETIC_FEATURE_'+tenant.upper(),'receipt':len(self.receipts)+1}
        self.receipts.append(result);self.cache[key]=result
        return 200,{**result,'cached':False}


def main():
    model=json.loads(Path('/app/model.json').read_text())
    config=json.loads(Path('/app/config.json').read_text())
    service=Service(model,config['strict'])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=4096:raise ValueError('size')
                body=json.loads(self.rfile.read(n))
                if not isinstance(body,dict):raise ValueError('schema')
                status,result=service.dispatch(self.path,self.headers,body)
            except (ValueError,TypeError,KeyError):status,result=400,{'error':'request'}
            Path('/tmp/receipts.json').write_text(json.dumps(service.receipts))
            raw=json.dumps(result,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    HTTPServer(('0.0.0.0',8080),Handler).serve_forever()


if __name__=='__main__':main()
