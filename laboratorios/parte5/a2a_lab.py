"""L20: A2A HTTP+JSON/SSE, callbacks autenticados e consumo vinculado à tarefa."""
import asyncio
from contextlib import ExitStack
import hashlib
import hmac
from importlib.metadata import version
import json
from pathlib import Path
import secrets
import sqlite3
import uuid

from google.protobuf.json_format import MessageToDict, ParseDict
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.types import (AgentCard, AgentCapabilities, AgentInterface, AgentSkill, SecurityScheme,
    HTTPAuthSecurityScheme, SecurityRequirement, StringList, Task, TaskState, TaskStatus,
    Message, Role, Part, Artifact, StreamResponse, TaskArtifactUpdateEvent, TaskStatusUpdateEvent,
    TaskPushNotificationConfig, AuthenticationInfo, SendMessageRequest, CancelTaskRequest,
    ListTaskPushNotificationConfigsResponse, TaskNotFoundError, UnsupportedOperationError)
from laboratorios.m1.auth import Authority
from laboratorios.m1.protocols import Server, Tasks, ContextBuilder, BearerMiddleware
from .common import database, new_output, write, seal, integrity


def copy_task(task):
    clone = Task(); clone.CopyFrom(task); return clone


def completed(task, owner):
    result = copy_task(task); result.status.state = TaskState.TASK_STATE_COMPLETED
    del result.artifacts[:]
    result.artifacts.append(Artifact(artifact_id='result-'+task.id, name='contrato',
        parts=[Part(text='RESULTADO_SINTETICO_'+owner)],
        metadata={'tenant':owner,'sourceTaskId':task.id,'resource':owner+'_contract'}))
    return result


class Specialist(Tasks):
    def __init__(self, path, callback_urls, events):
        super().__init__(events); self.path=Path(path); self.urls=set(callback_urls); self.configs={}
        with database(path) as db:
            db.executescript('CREATE TABLE tasks(id PRIMARY KEY,owner,state,body);'
                'CREATE TABLE configs(task_id,id,url,credential_hash,PRIMARY KEY(task_id,id));')

    def persist(self, task):
        with database(self.path) as db:
            db.execute('INSERT OR REPLACE INTO tasks VALUES(?,?,?,?)',
                (task.id,self.owners[task.id],TaskState.Name(task.status.state),json.dumps(MessageToDict(task),sort_keys=True)))

    async def on_message_send(self, params, context):
        task=await super().on_message_send(params,context); self.persist(task); return task

    async def on_cancel_task(self, params, context):
        task=await super().on_cancel_task(params,context); self.persist(task); return task

    async def on_message_send_stream(self, params, context):
        task=await self.on_message_send(params,context)
        # Caso 'esperar' começa em WORKING e termina aqui, em três eventos efetivos SSE.
        yield copy_task(task)
        result=completed(task,self.owner(context)); self.tasks[task.id]=result
        yield TaskArtifactUpdateEvent(task_id=task.id,context_id=task.context_id,
            artifact=result.artifacts[0],append=False,last_chunk=True)
        self.persist(result)
        yield TaskStatusUpdateEvent(task_id=task.id,context_id=task.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED))

    async def on_create_task_push_notification_config(self, params, context):
        self.require(params.task_id,context)
        if params.url not in self.urls or params.authentication.scheme.lower()!='bearer' or not params.authentication.credentials:
            raise UnsupportedOperationError('Callback fora dos destinos locais aprovados')
        cfg=TaskPushNotificationConfig();cfg.CopyFrom(params);cfg.id=cfg.id or uuid.uuid4().hex
        self.configs[(cfg.task_id,cfg.id)]=cfg
        with database(self.path) as db:
            db.execute('INSERT OR REPLACE INTO configs VALUES(?,?,?,?)',
                (cfg.task_id,cfg.id,cfg.url,hashlib.sha256(cfg.authentication.credentials.encode()).hexdigest()))
        return cfg

    async def on_get_task_push_notification_config(self, params, context):
        self.require(params.task_id,context)
        if (params.task_id,params.id) not in self.configs:raise TaskNotFoundError('Configuração ausente')
        return self.configs[(params.task_id,params.id)]

    async def on_list_task_push_notification_configs(self, params, context):
        self.require(params.task_id,context)
        return ListTaskPushNotificationConfigsResponse(configs=[v for k,v in self.configs.items() if k[0]==params.task_id])

    async def on_delete_task_push_notification_config(self, params, context):
        self.require(params.task_id,context);self.configs.pop((params.task_id,params.id),None)
        with database(self.path) as db:
            db.execute('DELETE FROM configs WHERE task_id=? AND id=?',(params.task_id,params.id))

    async def emit(self, tid, payload, bad_source=False):
        results=[]
        async with httpx.AsyncClient(timeout=10,trust_env=False,follow_redirects=False) as wire:
            for (task_id,_),cfg in self.configs.items():
                if task_id!=tid:continue
                response=await wire.post(cfg.url,json=MessageToDict(payload),headers={
                    'Authorization':'Bearer '+('invalid' if bad_source else cfg.authentication.credentials),
                    'X-A2A-Notification-Token':cfg.token,'Content-Type':'application/a2a+json'})
                results.append({'profile':cfg.url.rsplit('/',1)[1],'status':response.status_code,'body':response.json()})
        return results


class Receiver:
    def __init__(self,path):
        self.path=Path(path);self.secret=secrets.token_urlsafe(24);self.tokens={}
        with database(path) as db:
            db.executescript('CREATE TABLE expected(task PRIMARY KEY,context,tenant,state);'
              'CREATE TABLE consumed(task,artifact,digest,PRIMARY KEY(task,artifact));'
              'CREATE TABLE receipts(id INTEGER PRIMARY KEY,profile,task,artifact,tenant,resource,text);'
              'CREATE TABLE incoming(id INTEGER PRIMARY KEY,profile,expected_task,status,reason,payload);')

    def register(self,task,owner):
        token=secrets.token_urlsafe(24);self.tokens[token]=task.id
        with database(self.path) as db:
            db.execute('INSERT INTO expected VALUES(?,?,?,?)',(task.id,task.context_id,owner,'working'))
        return token

    def cancel(self,tid):
        with database(self.path) as db:db.execute("UPDATE expected SET state='canceled' WHERE task=?",(tid,))

    def accept(self,profile,tid,event):
        # Contrato de consumo da aplicação: aceita apenas tarefa terminal com um artefato completo.
        if not event.HasField('task') or len(event.task.artifacts)!=1:
            return 400,'not_complete_task'
        task=event.task;artifact=task.artifacts[0]
        metadata=dict(artifact.metadata);value=MessageToDict(event)
        digest=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with database(self.path,timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            expected=db.execute('SELECT context,tenant,state FROM expected WHERE task=?',(tid,)).fetchone()
            old=db.execute('SELECT digest FROM consumed WHERE task=? AND artifact=?',(tid,artifact.artifact_id)).fetchone()
            if profile=='strict':
                if (not expected or task.id!=tid or task.context_id!=expected[0]
                    or metadata.get('tenant')!=expected[1] or metadata.get('sourceTaskId')!=tid
                    or metadata.get('resource')!=expected[1]+'_contract'
                    or task.status.state!=TaskState.TASK_STATE_COMPLETED):return 403,'binding'
                if old:return (200,'duplicate') if old[0]==digest else (409,'conflict')
                if expected[2]!='working':return 409,'terminal_local_state'
                db.execute('INSERT INTO consumed VALUES(?,?,?)',(tid,artifact.artifact_id,digest))
                db.execute("UPDATE expected SET state='completed' WHERE task=?",(tid,))
            db.execute('INSERT INTO receipts(profile,task,artifact,tenant,resource,text) VALUES(?,?,?,?,?,?)',
                (profile,task.id,artifact.artifact_id,metadata.get('tenant'),metadata.get('resource'),artifact.parts[0].text))
        return 200,'consumed'

    def app(self):
        async def receive(request):
            profile=request.path_params['profile'];payload=await request.json()
            token=request.headers.get('X-A2A-Notification-Token','');tid=self.tokens.get(token)
            auth=request.headers.get('Authorization','').removeprefix('Bearer ')
            status,reason=401,'source'
            if hmac.compare_digest(auth,self.secret) and tid:
                try:status,reason=self.accept(profile,tid,ParseDict(payload,StreamResponse()))
                except (ValueError,KeyError):status,reason=400,'schema'
            with database(self.path) as db:
                db.execute('INSERT INTO incoming(profile,expected_task,status,reason,payload) VALUES(?,?,?,?,?)',
                    (profile,tid,status,reason,json.dumps(payload,sort_keys=True)))
            return JSONResponse({'reason':reason},status)
        return Starlette(routes=[Route('/{profile}',receive,methods=['POST'])])


def card(url):
    return AgentCard(name='Especialista L20',description='Resultados sintéticos e callbacks locais',version='1.0',
        supported_interfaces=[AgentInterface(url=url,protocol_binding='HTTP+JSON',protocol_version='1.0')],
        capabilities=AgentCapabilities(streaming=True,push_notifications=True),default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],skills=[AgentSkill(id='contract',name='Contrato',description='Artefato sintético',tags=['lab'])],
        security_schemes={'bearer':SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme='bearer',bearer_format='JWT'))},
        security_requirements=[SecurityRequirement(schemes={'bearer':StringList()})])


async def exercise(authority,url,callback_url,tasks,receiver,out):
    checks=[];callbacks=[]
    def check(name,ok,observed):
        checks.append({'case':name,'passed':bool(ok),'observed':observed});write(out/'checks_partial.json',checks)
    async with httpx.AsyncClient(timeout=15,trust_env=False) as wire:
        tokens={}
        for subject in ('alpha','beta'):
            r=await wire.post(authority.issuer+'/token',auth=(subject,authority.clients[subject]),
                data={'grant_type':'client_credentials','resource':url,'scope':'tasks:operate'})
            r.raise_for_status();tokens[subject]=r.json()['access_token']
        agent_card=await A2ACardResolver(wire,url).get_agent_card();write(out/'agent_card.json',MessageToDict(agent_card))
        check('card_version',agent_card.supported_interfaces[0].protocol_version=='1.0',MessageToDict(agent_card.capabilities))
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+tokens['alpha']},timeout=15,trust_env=False) as transport:
            sdk=ClientFactory(ClientConfig(httpx_client=transport,streaming=False,supported_protocol_bindings=["HTTP+JSON"])).create(agent_card)
            def message():return SendMessageRequest(message=Message(message_id=uuid.uuid4().hex,
                role=Role.ROLE_USER,parts=[Part(text='esperar')],metadata={'tenant':'beta'}))
            base={}
            for label in ('legitimate','wrong_task','wrong_context','wrong_tenant','wrong_artifact','late','source_unknown'):
                responses=[e async for e in sdk.send_message(message())];task=responses[-1].task;base[label]=task
                task_token=receiver.register(task,'alpha')
                for profile in ('weak','strict'):
                    config=await sdk.create_task_push_notification_config(TaskPushNotificationConfig(task_id=task.id,
                        url=callback_url+'/'+profile,token=task_token,authentication=AuthenticationInfo(scheme='Bearer',credentials=receiver.secret)))
                    check('config_'+label+'_'+profile,config.task_id==task.id and config.url==callback_url+'/'+profile,{'task':config.task_id,'url':config.url})
            # Cliente independente no fio cria a tarefa de beta; metadado não troca principal.
            r=await wire.post(url+'/message:send',headers={'Authorization':'Bearer '+tokens['beta'],'A2A-Version':'1.0'},
                              json={'message':{'messageId':uuid.uuid4().hex,'role':'ROLE_USER','parts':[{'text':'esperar'}]}})
            r.raise_for_status();beta=ParseDict(r.json()['task'],Task())
            check('wire_beta_created',tasks.owners[beta.id]=='beta',{'task':beta.id,'context':beta.context_id})
            for label,method,path,body in [
                ('cross_read','GET','/tasks/'+base['legitimate'].id,None),
                ('cross_cancel','POST','/tasks/'+base['legitimate'].id+':cancel',{}),
                ('cross_context','POST','/message:send',{'message':{'messageId':uuid.uuid4().hex,
                  'contextId':base['legitimate'].context_id,'role':'ROLE_USER','parts':[{'text':'esperar'}]}})]:
                r=await wire.request(method,url+path,json=body,headers={'Authorization':'Bearer '+tokens['beta'],'A2A-Version':'1.0'})
                check(label,r.status_code==404,{'status':r.status_code,'body':r.json()})
            canceled=await sdk.cancel_task(CancelTaskRequest(id=base['late'].id));receiver.cancel(canceled.id)
            check('cancel',canceled.status.state==TaskState.TASK_STATE_CANCELED,TaskState.Name(canceled.status.state))
            # Configuração de saída arbitrária não recebe I/O.
            r=await wire.post(url+'/tasks/'+base['legitimate'].id+'/pushNotificationConfigs',
                headers={'Authorization':'Bearer '+tokens['alpha'],'A2A-Version':'1.0'},
                json={'url':'http://127.0.0.1:1/unapproved','authentication':{'scheme':'Bearer','credentials':'fixture'}})
            check('unapproved_callback',r.status_code>=400,r.status_code)
            streaming=ClientFactory(ClientConfig(httpx_client=transport,streaming=True,supported_protocol_bindings=["HTTP+JSON"])).create(agent_card)
            events=[MessageToDict(e) async for e in streaming.send_message(message())]
            write(out/'sse_events.json',events)
            check('sse_three_events',len(events)==3 and 'task' in events[0] and 'artifactUpdate' in events[1] and 'statusUpdate' in events[2],events)
            check('sse_terminal',events[-1]['statusUpdate']['status']['state']=='TASK_STATE_COMPLETED',events[-1])
            for label,task in base.items():
                result=completed(task,'alpha')
                if label=='wrong_task':result=completed(beta,'beta')
                if label=='wrong_context':result.context_id=beta.context_id
                if label=='wrong_tenant':result.artifacts[0].metadata['tenant']='beta'
                if label=='wrong_artifact':result.artifacts[0].metadata['sourceTaskId']=beta.id
                payload=StreamResponse(task=result)
                outcomes=await tasks.emit(task.id,payload,bad_source=label=='source_unknown')
                callbacks.append({'case':label,'expected_task':task.id,'payload':MessageToDict(payload),'outcomes':outcomes})
                if label=='legitimate':
                    callbacks.append({'case':'duplicate','expected_task':task.id,'payload':MessageToDict(payload),
                                      'outcomes':await tasks.emit(task.id,payload)})
                    payload.task.artifacts[0].parts[0].text='CONTEUDO_TROCADO'
                    callbacks.append({'case':'conflict','expected_task':task.id,'payload':MessageToDict(payload),
                                      'outcomes':await tasks.emit(task.id,payload)})
    return checks,callbacks


def run(directory):
    out=new_output(directory);events=[]
    with ExitStack() as stack:
        issuer,agent,callback=Server(),Server(),Server()
        authority=Authority(issuer.url);authority.resources={agent.url:'tasks:operate'}
        receiver=Receiver(out/'receiver.sqlite');callback.start(receiver.app());stack.callback(callback.close)
        tasks=Specialist(out/'specialist.sqlite',[callback.url+'/weak',callback.url+'/strict'],events)
        app=Starlette(routes=create_agent_card_routes(card(agent.url))+create_rest_routes(tasks,ContextBuilder()))
        agent.start(BearerMiddleware(app,authority,agent.url,events));stack.callback(agent.close)
        issuer.start(authority.app());stack.callback(issuer.close)
        checks,callbacks=asyncio.run(exercise(authority,agent.url,callback.url,tasks,receiver,out))
        write(out/'results.json',{'lab':'L20','checks':checks,'callbacks':callbacks,'sdk':version('a2a-sdk'),
            'protocol':'1.0','transport':'HTTP+JSON and SSE','independent_client':'httpx; same author',
            'limits':['no LLM','loopback without TLS','persisted audit, no process restart qualification',
                      'task-specific local callback credentials, no external federation']})
        write(out/'server_events.json',events);write(out/'issuer_events.json',authority.events)
    seal(out);return verify(out)


def verify(directory):
    out=Path(directory);integrity(out);r=json.loads((out/'results.json').read_text(encoding='utf-8'))
    assert all(c['passed'] for c in r['checks']) and len(r['checks'])==23
    assert len(r['callbacks'])==9 and {x['case'] for x in r['callbacks']}=={
        'legitimate','duplicate','conflict','wrong_task','wrong_context','wrong_tenant','wrong_artifact','late','source_unknown'}
    with database(out/'receiver.sqlite') as db:
        receipts=db.execute('SELECT profile,task,tenant,resource,text FROM receipts').fetchall()
        incoming=db.execute('SELECT profile,expected_task,status,reason,payload FROM incoming ORDER BY id').fetchall()
        assert db.execute('SELECT count(*) FROM consumed').fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM expected WHERE state='canceled'").fetchone()[0]==1
    assert len(incoming)==18 and len(receipts)==9
    flattened=[(c,o) for c in r['callbacks'] for o in c['outcomes']]
    for (case,outcome),row in zip(flattened,incoming,strict=True):
        assert (outcome['profile'],case['expected_task'],outcome['status'],outcome['body']['reason'])==row[:4]
        assert json.loads(row[4])==case['payload']
        good = case['case'] in ('legitimate','duplicate') if outcome['profile']=='strict' else case['case']!='source_unknown'
        assert (outcome['status']==200)==good
    assert sum(x[0]=='weak' for x in receipts)==8 and sum(x[0]=='strict' for x in receipts)==1
    events=json.loads((out/'sse_events.json').read_text(encoding='utf-8'))
    for e in events:ParseDict(e,StreamResponse())
    with database(out/'specialist.sqlite') as db:
        assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==9
        assert db.execute('SELECT count(*) FROM configs').fetchone()[0]==14
    return {'lab':'L20','protocol_checks':23,'tasks':9,'sse_events':3,'callbacks':18,
            'consumptions':{'weak':8,'strict':1},'passed':True}
