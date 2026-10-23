"""Especialista A2A, ferramenta MCP, worker isolado e recurso com autoridade viva."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import uuid

import httpx
import httpx2
import jwt
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.types import (Message, Part, Role, Artifact, AgentCard, AgentInterface,
    AgentCapabilities, AgentSkill, SecurityScheme, HTTPAuthSecurityScheme,
    SecurityRequirement, StringList, TaskState, CancelTaskRequest, SendMessageRequest)

from laboratorios.m1.auth import Authority
from laboratorios.m1.protocols import Server, Tasks, ContextBuilder, BearerMiddleware
from laboratorios.parte7.deployment import BASE,HARDEN,docker
from .common import new_output, read, write, canonical, digest, seal, integrity, database

MCP_VERSION='2026-07-28'
FIELDS={'operation','task','context','revision','resource','destination','epoch'}
WORKER='''import hashlib,json,os,socket,sys
a=json.loads(sys.stdin.read())
try:open('/root/forbidden','w').write('x');root_write=True
except OSError:root_write=False
s=socket.socket();s.settimeout(.3)
try:s.connect(('203.0.113.1',80));network=True
except OSError:network=False
finally:s.close()
print(json.dumps({'digest':hashlib.sha256(json.dumps(a,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'uid':os.getuid(),'root_write':root_write,'network':network}))
'''


def fingerprint(action):
    if set(action)!=FIELDS or any(not isinstance(action[k],str) or not action[k] for k in FIELDS-{'epoch'}):
        raise ValueError('action_schema')
    if type(action['epoch']) is not int or action['epoch']<0:raise ValueError('epoch')
    return digest(action)


def isolated(action):
    name='book-l36-worker-'+uuid.uuid4().hex[:10]
    try:
        args=['docker','run','--rm','-i','--name',name,'--pull','never',*HARDEN,
              '--user','10001:10001','--cpus','1','--network','none',BASE,'python','-c',WORKER]
        p=subprocess.run(args,input=canonical(action),capture_output=True,timeout=20)
        if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
        result=json.loads(p.stdout)
        if result!={'digest':fingerprint(action),'uid':10001,'root_write':False,'network':False}:
            raise ValueError('worker_contract')
        return result
    finally:docker('rm','-f',name,check=False)


class Ledger:
    def __init__(self,path,strict=True):
        self.path=Path(path);self.strict=strict
        with database(self.path) as db:
            db.executescript('CREATE TABLE IF NOT EXISTS control(id PRIMARY KEY,epoch);'
              'INSERT OR IGNORE INTO control VALUES(1,0);'
              'CREATE TABLE IF NOT EXISTS tasks(id PRIMARY KEY,context,owner,state);'
              'CREATE TABLE IF NOT EXISTS approvals(id PRIMARY KEY,owner,digest,epoch);'
              'CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY,operation UNIQUE,digest,owner,resource,destination);'
              'CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,operation,reason,receipt);')

    def register(self,task,owner):
        with database(self.path) as db:db.execute('INSERT INTO tasks VALUES(?,?,?,?)',(task.id,task.context_id,owner,'active'))

    def approve(self,action,owner):
        fingerprint(action)
        if action['resource']!=owner+'_contract' or action['destination']!='portal_'+owner:
            raise PermissionError('approval_policy')
        key=uuid.uuid4().hex
        with database(self.path) as db:
            epoch=db.execute('SELECT epoch FROM control').fetchone()[0]
            if action['epoch']!=epoch:raise PermissionError('epoch')
            task=db.execute('SELECT context,owner,state FROM tasks WHERE id=?',(action['task'],)).fetchone()
            if task!=(action['context'],owner,'active'):raise PermissionError('task_binding')
            db.execute('INSERT INTO approvals VALUES(?,?,?,?)',(key,owner,fingerprint(action),epoch))
        return key

    def revoke(self):
        with database(self.path) as db:db.execute('UPDATE control SET epoch=epoch+1')

    def cancel(self,task):
        with database(self.path) as db:db.execute("UPDATE tasks SET state='canceled' WHERE id=?",(task,))

    def execute(self,action,owner,ticket,worker=isolated,lost_reply=False):
        h=fingerprint(action)
        # A computação isolada não recebe credenciais nem o arquivo do recurso.
        observed=worker(action)
        with database(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,digest FROM receipts WHERE operation=?',(action['operation'],)).fetchone()
            epoch=db.execute('SELECT epoch FROM control').fetchone()[0]
            approval=db.execute('SELECT owner,digest,epoch FROM approvals WHERE id=?',(ticket,)).fetchone()
            task=db.execute('SELECT context,owner,state FROM tasks WHERE id=?',(action['task'],)).fetchone()
            reason='committed';receipt=None
            if self.strict and (action['epoch']!=epoch):reason='revoked'
            elif self.strict and task!=(action['context'],owner,'active'):reason='task_binding'
            elif self.strict and approval!=(owner,h,epoch):reason='approval_binding'
            elif self.strict and (action['resource']!=owner+'_contract' or action['destination']!='portal_'+owner):reason='resource_policy'
            elif old:
                reason='replay' if old[1]==h else 'operation_conflict';receipt=old[0] if old[1]==h else None
            else:
                receipt=db.execute('INSERT INTO receipts(operation,digest,owner,resource,destination) VALUES(?,?,?,?,?)',
                    (action['operation'],h,owner,action['resource'],action['destination'])).lastrowid
            db.execute('INSERT INTO events(operation,reason,receipt) VALUES(?,?,?)',(action['operation'],reason,receipt))
        if lost_reply and reason=='committed':return {'state':'unknown','worker':observed}
        return {'state':reason,'receipt':receipt,'worker':observed}


class Specialist(Tasks):
    async def on_message_send(self,params,context):
        task=await super().on_message_send(params,context)
        if task.status.state==TaskState.TASK_STATE_COMPLETED:
            hostile=any(p.text=='hostile' for p in params.message.parts)
            owner=self.owner(context)
            proposal={'resource':'beta_contract' if hostile else owner+'_contract',
                      'destination':'collector' if hostile else 'portal_'+owner,'revision':'2' if hostile else '1'}
            del task.artifacts[:]
            task.artifacts.append(Artifact(artifact_id=uuid.uuid4().hex,name='proposal',parts=[Part(text=json.dumps(proposal))]))
        return task


def mcp_app(authority,url,ledgers):
    class Verifier(TokenVerifier):
        async def verify_token(self,token):
            try:
                c=authority.validate(token,url)
                return AccessToken(token=token,client_id=c['sub'],scopes=c['scope'].split(),
                    expires_at=c['exp'],resource=c['aud'],subject=c['sub'],claims=c)
            except jwt.InvalidTokenError:return None
    server=MCPServer('L36 operações',token_verifier=Verifier(),log_level='CRITICAL',
       auth=AuthSettings(issuer_url=authority.issuer,resource_server_url=url,
                        required_scopes=['operations:execute'],validate_token_resource=True))
    @server.tool()
    def execute(profile:str,action:dict,ticket:str,lost_reply:bool=False)->dict:
        """Executa proposta com autorização no recurso; campos não são autoridade."""
        if profile not in ledgers:raise ValueError('profile')
        return ledgers[profile].execute(action,get_access_token().claims['sub'],ticket,lost_reply=lost_reply)
    return server.streamable_http_app(json_response=True,stateless_http=True)


def card(url):
    return AgentCard(name='L36 especialista',description='Propostas sintéticas, incluindo interlocutor malicioso',
        version='1.0.0',supported_interfaces=[AgentInterface(url=url,protocol_binding='HTTP+JSON',protocol_version='1.0')],
        capabilities=AgentCapabilities(streaming=False),default_input_modes=['text/plain'],default_output_modes=['text/plain'],
        skills=[AgentSkill(id='proposal',name='Proposta',description='Propõe; não autoriza',tags=['lab'])],
        security_schemes={'bearer':SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme='bearer',bearer_format='JWT'))},
        security_requirements=[SecurityRequirement(schemes={'bearer':StringList()})])


async def exercise(authority,mcp_url,a2a_url,ledgers,out):
    observations=[];artifacts=[];credentials=[]
    async with httpx.AsyncClient(timeout=60,trust_env=False) as wire:
        meta=(await wire.get(authority.issuer+'/.well-known/oauth-authorization-server')).json()
        write(out/'issuer_metadata.json',meta);write(out/'jwks.json',(await wire.get(meta['jwks_uri'])).json())
        async def token(owner,url,scope):
            r=await wire.post(meta['token_endpoint'],auth=(owner,authority.clients[owner]),
                data={'grant_type':'client_credentials','resource':url,'scope':scope});r.raise_for_status()
            value=r.json()['access_token']
            claims=authority.validate(value,url,scope)
            credentials.append({k:claims[k] for k in ('sub','aud','iat','exp','scope')})
            write(out/'credential_validity.json',credentials)
            return value
        mt=await token('alpha',mcp_url,'operations:execute');at=await token('alpha',a2a_url,'tasks:operate')
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+at},timeout=30,trust_env=False) as transport:
            resolved=await A2ACardResolver(transport,a2a_url).get_agent_card()
            ac=ClientFactory(ClientConfig(httpx_client=transport,streaming=False,supported_protocol_bindings=['HTTP+JSON'])).create(resolved)
            async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+mt},timeout=60) as mtp:
                async with Client(streamable_http_client(mcp_url,http_client=mtp),mode=MCP_VERSION,cache=None) as mc:
                    listing=await mc.list_tools();write(out/'catalog.json',[t.model_dump(by_alias=True,exclude_none=True) for t in listing.tools])
                    for case in ('legitimate','hostile_replan','replay','conflict','direct','revoked','lost_reply','canceled'):
                        # Não estender o TTL para acomodar duração variável do Docker.
                        transport.headers['Authorization']='Bearer '+await token('alpha',a2a_url,'tasks:operate')
                        mtp.headers['Authorization']='Bearer '+await token('alpha',mcp_url,'operations:execute')
                        waiting=case=='canceled'
                        message=Message(message_id=uuid.uuid4().hex,role=Role.ROLE_USER,
                            parts=[Part(text='esperar' if waiting else 'hostile' if case=='hostile_replan' else 'legitimate')])
                        results=[item async for item in ac.send_message(SendMessageRequest(message=message))]
                        task=results[-1].task
                        if not task.id:raise ValueError('missing A2A task')
                        artifacts.append({'case':case,'task':MessageToDict(task)})
                        epoch=1 if case in ('lost_reply','canceled') else 0
                        base={'operation':case,'task':task.id,'context':task.context_id,'revision':'1',
                              'resource':'alpha_contract','destination':'portal_alpha','epoch':epoch}
                        tickets={}
                        for profile,ledger in ledgers.items():
                            ledger.register(task,'alpha');tickets[profile]=ledger.approve(base,'alpha')
                        action=deepcopy(base)
                        if case=='hostile_replan':action.update(json.loads(task.artifacts[0].parts[0].text))
                        if case=='revoked':
                            for ledger in ledgers.values():ledger.revoke()
                        if waiting:
                            canceled=await ac.cancel_task(CancelTaskRequest(id=task.id))
                            assert canceled.status.state==TaskState.TASK_STATE_CANCELED
                            for ledger in ledgers.values():ledger.cancel(task.id)
                        for profile in ledgers:
                            async def invoke(a,label):
                                result=await mc.call_tool('execute',{'profile':profile,'action':a,
                                     'ticket':'missing' if case=='direct' else tickets[profile],
                                     'lost_reply':case=='lost_reply' and label=='first'})
                                value=result.structured_content or json.loads(result.content[0].text)
                                observations.append({'case':case,'profile':profile,'call':label,'action':deepcopy(a),'result':value})
                                write(out/'observations_partial.json',observations)
                                return value
                            await invoke(action,'first')
                            if case in ('replay','lost_reply'):await invoke(action,'retry')
                            if case=='conflict':await invoke({**action,'destination':'collector'},'changed')
        # Implementação alternativa de cliente, mesmo autor: chamada direta JSON-RPC.
        mt=await token('alpha',mcp_url,'operations:execute')
        at=await token('alpha',a2a_url,'tasks:operate')
        headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json',
                 'Authorization':'Bearer '+mt,'MCP-Protocol-Version':MCP_VERSION,'MCP-Method':'tools/call','MCP-Name':'execute'}
        direct={**base,'operation':'wire','epoch':1}
        payload={'jsonrpc':'2.0','id':991,'method':'tools/call','params':{'name':'execute',
            'arguments':{'profile':'strict','action':direct,'ticket':'absent'},'_meta':{
                'io.modelcontextprotocol/protocolVersion':MCP_VERSION,
                'io.modelcontextprotocol/clientCapabilities':{},'io.modelcontextprotocol/clientInfo':{'name':'l36-wire','version':'1.0'}}}}
        r=await wire.post(mcp_url,headers=headers,json=payload)
        wrong=await wire.post(mcp_url,headers={**headers,'Authorization':'Bearer '+at},json=payload)
        unauth=await wire.post(a2a_url+'/message:send',json={'message':{'messageId':'x','role':'ROLE_USER','parts':[{'text':'x'}]}})
        write(out/'wire.json',{'direct':{'status':r.status_code,'body':r.json()},
                              'wrong_audience':wrong.status_code,'a2a_unauthenticated':unauth.status_code})
    write(out/'observations.json',observations);write(out/'tasks.json',artifacts)
    return observations


def run(directory):
    out=new_output(directory);events=[]
    ledgers={name:Ledger(out/(name+'.sqlite'),name=='strict') for name in ('weak','strict')}
    with ExitStack() as stack:
        issuer,tool,agent=Server(),Server(),Server();authority=Authority(issuer.url)
        url=tool.url+'/mcp';authority.resources={url:'operations:execute',agent.url:'tasks:operate'}
        specialist=Specialist(events)
        application=Starlette(routes=create_agent_card_routes(card(agent.url))+create_rest_routes(specialist,ContextBuilder()))
        agent.start(BearerMiddleware(application,authority,agent.url,events));stack.callback(agent.close)
        tool.start(mcp_app(authority,url,ledgers));stack.callback(tool.close)
        issuer.start(authority.app());stack.callback(issuer.close)
        observations=asyncio.run(exercise(authority,url,agent.url,ledgers,out))
        write(out/'issuer_events.json',authority.events);write(out/'a2a_events.json',events)
    for profile in ledgers:
        reopened=Ledger(out/(profile+'.sqlite'),profile=='strict')
        with database(reopened.path) as db:receipts=db.execute('SELECT id,operation,digest,owner,resource,destination FROM receipts ORDER BY id').fetchall()
        write(out/(profile+'_receipts.json'),receipts)
    write(out/'results.json',{'mcp_protocol':MCP_VERSION,'a2a_protocol':'1.0','base':BASE,
        'approval':'fixture de decisão humana, sem aprovação de uma pessoa real',
        'cases':8,'tool_calls':len(observations)+1,'real_llm':False,'external_review':False,
        'limits':['local client_credentials; no browser OAuth/TLS/federation',
                  'worker Docker isolated; authority and SQLite resource trusted on host',
                  'lost_reply is application fault returning unknown after commit, not a network timeout',
                  'reopen database after servers close; no full distributed restart']})
    seal(out);return verify(out)


def verify(directory):
    out=Path(directory);integrity(out);rows=read(out/'observations.json')
    assert len(rows)==22
    for row in rows:
        assert row['result']['worker']=={'digest':fingerprint(row['action']),'uid':10001,'root_write':False,'network':False}
    strict=[r for r in rows if r['profile']=='strict']
    state={(r['case'],r['call']):r['result']['state'] for r in strict}
    assert state=={('legitimate','first'):'committed',('hostile_replan','first'):'approval_binding',
       ('replay','first'):'committed',('replay','retry'):'replay',('conflict','first'):'committed',
       ('conflict','changed'):'approval_binding',('direct','first'):'approval_binding',
       ('revoked','first'):'revoked',('lost_reply','first'):'unknown',('lost_reply','retry'):'replay',
       ('canceled','first'):'task_binding'}
    wire=read(out/'wire.json');assert wire['direct']['status']==200 and wire['wrong_audience']==401 and wire['a2a_unauthenticated']==401
    content=wire['direct']['body']['result']
    value=content.get('structuredContent') or json.loads(content['content'][0]['text'])
    assert value['state']=='task_binding'
    counts={}
    for profile in ('weak','strict'):
        with database(out/(profile+'.sqlite')) as db:
            receipts=[list(r) for r in db.execute('SELECT id,operation,digest,owner,resource,destination FROM receipts ORDER BY id')]
            assert db.execute('SELECT epoch FROM control').fetchone()[0]==1
        assert receipts==read(out/(profile+'_receipts.json'));counts[profile]=len(receipts)
        if profile=='strict':assert all(r[4]=='alpha_contract' and r[5]=='portal_alpha' for r in receipts)
    assert counts=={'weak':8,'strict':4}
    return {'lab':'L36','cases':8,'sdk_tool_calls':22,'wire_tool_calls':1,'receipts':counts,
            'real_isolated_workers':23,'external_review':False}
