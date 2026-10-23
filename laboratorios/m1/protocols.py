"""SDKs oficiais sobre HTTP real; perfil local e limitado de interoperabilidade."""
import argparse
import asyncio
from contextlib import ExitStack
from importlib.metadata import version
import json
from pathlib import Path
import socket
import threading
import time
import uuid

import httpx
import httpx2
import jwt
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.requests import Request
from mcp import Client as MCPClient
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.auth.middleware.auth_context import get_access_token
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.server.routes import create_agent_card_routes, create_rest_routes, ServerCallContextBuilder
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types import (AgentCard, AgentInterface, AgentCapabilities, AgentSkill,
    Artifact, Message, Part, Task, TaskStatus, TaskState, Role, SendMessageRequest,
    GetTaskRequest, CancelTaskRequest, ListTasksResponse, TaskNotFoundError,
    TaskNotCancelableError, UnsupportedOperationError, SecurityScheme,
    HTTPAuthSecurityScheme, SecurityRequirement, StringList)

from .auth import Authority
from .common import write, seal


class Server:
    def __init__(self):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.url = 'http://127.0.0.1:' + str(self.socket.getsockname()[1])

    def start(self, app):
        self.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1',
                                     log_level='critical', access_log=False))
        self.thread = threading.Thread(target=self.server.run,
                          kwargs={'sockets': [self.socket]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic()+20
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Servidor HTTP não iniciou')
            time.sleep(.02)
        return self

    def close(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError('Servidor não encerrou')


def mcp_app(authority, audience, events):
    class Verifier(TokenVerifier):
        async def verify_token(self, token):
            try:
                claims = authority.validate(token, audience)
                events.append({'operation': 'authenticate', 'allowed': True, 'subject': claims['sub']})
                return AccessToken(token=token, client_id=claims['sub'],
                    scopes=claims['scope'].split(), expires_at=claims['exp'],
                    resource=claims['aud'], subject=claims['sub'], claims=claims)
            except jwt.InvalidTokenError:
                events.append({'operation': 'authenticate', 'allowed': False})
                return None
    server = MCPServer('Contratos M1', log_level='CRITICAL', token_verifier=Verifier(), auth=AuthSettings(
        issuer_url=authority.issuer, resource_server_url=audience,
        required_scopes=['contracts:read'], validate_token_resource=True))
    @server.tool()
    def read_contract(resource: str) -> dict:
        """Lê apenas o contrato da identidade validada; resource não concede autoridade."""
        principal = get_access_token().claims
        allowed = resource == principal['tenant'] + '_contract'
        events.append({'operation': 'read_contract', 'subject': principal['sub'],
                       'resource': resource, 'allowed': allowed})
        if not allowed:
            return {'allowed': False, 'error': 'resource_policy'}
        return {'allowed': True, 'resource': resource,
                'text': 'CONTRATO_SINTETICO_' + principal['tenant']}
    return server.streamable_http_app(json_response=True, stateless_http=True)


class ContextBuilder(ServerCallContextBuilder):
    def build(self, request):
        return ServerCallContext(state={'principal': request.scope['m1_principal'],
            'headers': {'a2a-version': request.headers.get('A2A-Version', '')}})


class Tasks(RequestHandler):
    """Estado em memória, sem filas, retomada após crash ou executor de LLM."""
    def __init__(self, events):
        self.tasks, self.owners, self.context_owners, self.events = {}, {}, {}, events

    def owner(self, context):
        return context.state['principal']['sub']

    def require(self, task_id, context):
        allowed = self.owners.get(task_id) == self.owner(context)
        self.events.append({'operation': 'task_access', 'task_id': task_id,
                            'subject': self.owner(context), 'allowed': allowed})
        if not allowed:
            raise TaskNotFoundError('Tarefa não disponível para esta identidade')
        return self.tasks[task_id]

    async def on_get_task(self, params, context):
        return self.require(params.id, context)

    async def on_list_tasks(self, params, context):
        return ListTasksResponse(tasks=[t for k, t in self.tasks.items()
                                        if self.owners[k] == self.owner(context)])

    async def on_cancel_task(self, params, context):
        task = self.require(params.id, context)
        if task.status.state != TaskState.TASK_STATE_WORKING:
            raise TaskNotCancelableError('Somente tarefa em execução nesta bancada')
        task.status.state = TaskState.TASK_STATE_CANCELED
        self.events.append({'operation': 'canceled', 'task_id': task.id, 'subject': self.owner(context)})
        return task

    async def on_message_send(self, params, context):
        message = params.message
        if message.task_id:
            self.require(message.task_id, context)
            raise UnsupportedOperationError('Continuação de tarefa não implementada no perfil M1')
        owner = self.owner(context)
        cid = message.context_id
        if cid and self.context_owners.get(cid) != owner:
            self.events.append({'operation': 'context_access', 'subject': owner, 'allowed': False})
            raise TaskNotFoundError('Contexto não disponível para esta identidade')
        cid = cid or str(uuid.uuid4())
        tid = str(uuid.uuid4())
        waiting = any(p.text == 'esperar' for p in message.parts)
        task = Task(id=tid, context_id=cid, history=[message],
                    status=TaskStatus(state=TaskState.TASK_STATE_WORKING if waiting
                                     else TaskState.TASK_STATE_COMPLETED))
        if not waiting:
            task.artifacts.append(Artifact(artifact_id=str(uuid.uuid4()), name='recibo',
                parts=[Part(text='ARTEFATO_SINTETICO_' + owner)]))
        self.tasks[tid], self.owners[tid], self.context_owners[cid] = task, owner, owner
        self.events.append({'operation': 'created', 'task_id': tid, 'context_id': cid,
                            'subject': owner, 'state': TaskState.Name(task.status.state)})
        return task

    async def unsupported(self, params, context):
        raise UnsupportedOperationError('Fora do perfil M1')

    on_create_task_push_notification_config = unsupported
    on_get_task_push_notification_config = unsupported
    on_delete_task_push_notification_config = unsupported
    on_list_task_push_notification_configs = unsupported
    on_get_extended_agent_card = unsupported

    async def on_message_send_stream(self, params, context):
        raise UnsupportedOperationError('Streaming fora do perfil M1')
        yield

    on_subscribe_to_task = on_message_send_stream


class BearerMiddleware:
    def __init__(self, app, authority, audience, events):
        self.app, self.authority, self.audience, self.events = app, authority, audience, events

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/.well-known/agent-card.json':
            return await self.app(scope, receive, send)
        request = Request(scope)
        status, reason = 401, 'invalid_token'
        try:
            header = request.headers.get('Authorization', '')
            if not header.startswith('Bearer '):
                raise jwt.InvalidTokenError()
            claims = self.authority.validate(header[7:], self.audience, 'tasks:operate')
            scope['m1_principal'] = claims
        except PermissionError:
            status, reason = 403, 'insufficient_scope'
        except jwt.InvalidTokenError:
            pass
        else:
            return await self.app(scope, receive, send)
        self.events.append({'operation': 'authenticate', 'allowed': False, 'reason': reason})
        return await JSONResponse({'error': reason}, status_code=status)(scope, receive, send)


def a2a_app(authority, url, events):
    card = AgentCard(name='Agente M1', description='Tarefas sintéticas e autorização de proprietário',
        version='1.0.0', supported_interfaces=[AgentInterface(url=url,
            protocol_binding='HTTP+JSON', protocol_version='1.0')],
        capabilities=AgentCapabilities(streaming=False), default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],
        skills=[AgentSkill(id='receipt', name='Recibo', description='Artefato sintético', tags=['lab'])],
        security_schemes={'bearer': SecurityScheme(http_auth_security_scheme=
            HTTPAuthSecurityScheme(scheme='bearer', bearer_format='JWT'))},
        security_requirements=[SecurityRequirement(schemes={'bearer': StringList()})])
    tasks = Tasks(events)
    app = Starlette(routes=create_agent_card_routes(card)+create_rest_routes(tasks, ContextBuilder()))
    return BearerMiddleware(app, authority, url, events), tasks


async def exercise(authority, mcp_url, a2a_url, events, out):
    checks = []
    def check(name, condition, observed):
        checks.append({'name': name, 'passed': bool(condition), 'observed': observed})
        write(out/'checks_partial.json', checks)
    async with httpx.AsyncClient(timeout=15, trust_env=False) as wire:
        metadata = (await wire.get(authority.issuer+'/.well-known/oauth-authorization-server')).json()
        keys = (await wire.get(metadata['jwks_uri'])).json()
        check('issuer_metadata_and_public_key', metadata['issuer'] == authority.issuer
              and len(keys['keys']) == 1, {'issuer': metadata['issuer'], 'kid': keys['keys'][0]['kid']})
        async def credential(subject, target, scope):
            r = await wire.post(metadata['token_endpoint'], auth=(subject, authority.clients[subject]),
                data={'grant_type': 'client_credentials', 'resource': target, 'scope': scope})
            r.raise_for_status()
            return r.json()['access_token']
        ma = await credential('alpha', mcp_url, 'contracts:read')
        aa = await credential('alpha', a2a_url, 'tasks:operate')
        ab = await credential('beta', a2a_url, 'tasks:operate')
        bad_client = await wire.post(metadata['token_endpoint'], auth=('alpha', 'wrong'), data={})
        check('issuer_invalid_client', bad_client.status_code == 401, bad_client.status_code)
        # Um cliente alternativo HTTP faz descoberta e chamadas JSON-RPC sem usar MCPClient.
        headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}
        missing = await wire.post(mcp_url, headers=headers, json=payload)
        challenge = missing.headers.get('www-authenticate', '')
        check('mcp_missing_bearer', missing.status_code == 401, missing.status_code)
        import re
        match = re.search(r'resource_metadata="([^"]+)"', challenge)
        check('mcp_resource_discovery_challenge', bool(match), challenge)
        if match:
            prm = (await wire.get(match[1])).json()
            check('mcp_resource_metadata', prm['resource'] == mcp_url and
                  authority.issuer in prm['authorization_servers'], prm)
        async with httpx2.AsyncClient(headers={'Authorization': 'Bearer '+ma}) as transport:
            async with MCPClient(streamable_http_client(mcp_url, http_client=transport), cache=None) as client:
                listing = await client.list_tools()
                check('mcp_sdk_tools_list', any(t.name == 'read_contract' for t in listing.tools),
                      {'tools': [t.name for t in listing.tools], 'protocol_version': client.protocol_version})
                own = await client.call_tool('read_contract', {'resource': 'alpha_contract'})
                foreign = await client.call_tool('read_contract', {'resource': 'beta_contract'})
                own_data = own.structured_content or json.loads(own.content[0].text)
                foreign_data = foreign.structured_content or json.loads(foreign.content[0].text)
                check('mcp_sdk_own_resource', own_data.get('allowed') is True, own_data)
                check('mcp_sdk_cross_tenant', foreign_data.get('allowed') is False, foreign_data)
                protocol = client.protocol_version
        headers['MCP-Protocol-Version'] = protocol
        headers['MCP-Method'] = 'tools/call'
        headers['MCP-Name'] = 'read_contract'
        headers['Authorization'] = 'Bearer '+ma
        call = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                'params': {'name': 'read_contract', 'arguments': {'resource': 'alpha_contract'},
                    '_meta': {'io.modelcontextprotocol/protocolVersion': protocol,
                              'io.modelcontextprotocol/clientCapabilities': {}}}}
        alternate = await wire.post(mcp_url, headers=headers, json=call)
        check('mcp_wire_client_own', alternate.status_code == 200 and
              'CONTRATO_SINTETICO_alpha' in alternate.text, alternate.json())
        call['params']['arguments']['resource'] = 'beta_contract'
        alternate = await wire.post(mcp_url, headers=headers, json=call)
        check('mcp_wire_client_cross_tenant', alternate.status_code == 200 and
              'CONTRATO_SINTETICO_beta' not in alternate.text and 'resource_policy' in alternate.text,
              alternate.json())
        for name, token, expected in [
            ('wrong_audience', authority.issue('alpha', a2a_url, 'contracts:read'), 401),
            ('expired', authority.issue('alpha', mcp_url, 'contracts:read', exp=int(time.time())-60), 401),
            ('wrong_scope', authority.issue('alpha', mcp_url, 'other'), 403),
            ('wrong_issuer', authority.issue('alpha', mcp_url, 'contracts:read', iss='http://invalid.local'), 401),
            ('signature', ma[:ma.rfind('.')+1]+'A'*342, 401)]:
            h = {**headers, 'Authorization': 'Bearer '+token}
            r = await wire.post(mcp_url, headers=h, json=payload)
            check('mcp_'+name, r.status_code == expected, r.status_code)
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer '+aa, 'A2A-Version': '1.0'}, timeout=15,
                                     trust_env=False) as transport:
            card = await A2ACardResolver(transport, a2a_url).get_agent_card()
            check('a2a_card_bearer', 'bearer' in card.security_schemes,
                  {'binding': card.supported_interfaces[0].protocol_binding,
                   'version': card.supported_interfaces[0].protocol_version})
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=transport,
                         supported_protocol_bindings=['HTTP+JSON'])).create(card)
            def message(text):
                return SendMessageRequest(message=Message(message_id=str(uuid.uuid4()),
                    role=Role.ROLE_USER, parts=[Part(text=text)], metadata={'tenant': 'beta'}))
            responses = [e async for e in client.send_message(message('gerar recibo'))]
            task = responses[-1].task
            check('a2a_sdk_artifact_principal_binding', task.status.state == TaskState.TASK_STATE_COMPLETED
                  and task.artifacts[0].parts[0].text == 'ARTEFATO_SINTETICO_alpha',
                  {'state': TaskState.Name(task.status.state), 'artifact': task.artifacts[0].parts[0].text})
            fetched = await client.get_task(GetTaskRequest(id=task.id))
            check('a2a_sdk_get_task', fetched.id == task.id, fetched.id)
            pending = [e async for e in client.send_message(message('esperar'))]
            working = pending[-1].task
            canceled = await client.cancel_task(CancelTaskRequest(id=working.id))
            check('a2a_sdk_cancel', canceled.status.state == TaskState.TASK_STATE_CANCELED,
                  TaskState.Name(canceled.status.state))
        ah = {'Authorization': 'Bearer '+ab, 'A2A-Version': '1.0'}
        for name, method, path, body in [
            ('read_other_task', 'GET', '/tasks/'+task.id, None),
            ('cancel_other_task', 'POST', '/tasks/'+task.id+':cancel', {}),
            ('reuse_other_context', 'POST', '/message:send', {'message': {'messageId': str(uuid.uuid4()),
                'contextId': task.context_id, 'role': 'ROLE_USER', 'parts': [{'text': 'gerar recibo'}]}})]:
            r = await wire.request(method, a2a_url+path, headers=ah, json=body)
            check('a2a_'+name, r.status_code == 404 and 'ARTEFATO_SINTETICO_alpha' not in r.text,
                  {'status': r.status_code, 'body': r.json()})
        for name, token, expected in [
            ('missing', '', 401), ('wrong_audience', ma, 401),
            ('expired', authority.issue('alpha', a2a_url, 'tasks:operate', exp=int(time.time())-60), 401),
            ('wrong_scope', authority.issue('alpha', a2a_url, 'other'), 403),
            ('wrong_issuer', authority.issue('alpha', a2a_url, 'tasks:operate', iss='http://invalid.local'), 401),
            ('signature', aa[:aa.rfind('.')+1]+'A'*342, 401)]:
            auth_headers = {'A2A-Version': '1.0'}
            if token:
                auth_headers['Authorization'] = 'Bearer '+token
            r = await wire.get(a2a_url+'/tasks/'+task.id, headers=auth_headers)
            check('a2a_'+name, r.status_code == expected, r.status_code)
        # Bearer não é single-use: reapresentação legítima é permitida; não prometer antirreplay.
        repeat = await wire.get(a2a_url+'/tasks/'+task.id,
            headers={'Authorization': 'Bearer '+aa, 'A2A-Version': '1.0'})
        check('a2a_bearer_reuse_is_not_replay_protection', repeat.status_code == 200, repeat.status_code)
    return checks


def run(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=False)
    events = {'mcp': [], 'a2a': []}
    with ExitStack() as stack:
        issuer, mcp, a2a = Server(), Server(), Server()
        authority = Authority(issuer.url)
        mcp_url = mcp.url+'/mcp'
        authority.resources = {mcp_url: 'contracts:read', a2a.url: 'tasks:operate'}
        issuer.start(authority.app()); stack.callback(issuer.close)
        mcp.start(mcp_app(authority, mcp_url, events['mcp'])); stack.callback(mcp.close)
        app, tasks = a2a_app(authority, a2a.url, events['a2a'])
        a2a.start(app); stack.callback(a2a.close)
        try:
            checks = asyncio.run(exercise(authority, mcp_url, a2a.url, events, out))
            report = {'version': 'M1-protocols-1.0', 'checks': checks,
                'passed': all(c['passed'] for c in checks),
                'packages': {p: version(p) for p in ('mcp', 'a2a-sdk', 'PyJWT', 'httpx', 'httpx2', 'uvicorn')},
                'limits': ['HTTP loopback; sem TLS, PKCE, OIDC, federação ou certificação OAuth.',
                          'SDK e cliente HTTP manual executados pelo mesmo autor; sem revisão independente.',
                          'Serviços em threads no mesmo processo; não constitui isolamento de código hostil.',
                          'A2A não executa LLM; estado volátil, sem streaming, push ou recuperação após crash.',
                          'Bearer reutilizável; não implementa antirreplay, DPoP, revogação ou rotação.',
                          'Política do recurso é implementada pela aplicação, não garantida pelo protocolo.']}
            write(out/'results.json', report)
        finally:
            write(out/'server_events.json', {**events, 'issuer': authority.events})
    seal(out)
    print(json.dumps({'passed': report['passed'], 'checks': len(checks),
                      'failures': [c for c in checks if not c['passed']]}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = run(args.out)
    raise SystemExit(0 if result['passed'] else 1)
