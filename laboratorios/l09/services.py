"""Dois processos HTTP em loopback, com recibos independentes em SQLite.

Este servidor é uma bancada local, não uma base para implantação pública.
Credenciais opacas são geradas por execução, passadas em memória e não registradas.
"""
from contextlib import AbstractContextManager, closing
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse

from .core import Action, Principal, read_decision, delivery_decision, retrieve


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token, payload=None, timeout=8):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise ValueError("O laboratório só admite HTTP para 127.0.0.1")
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Authorization": "Bearer " + token,
                  "Content-Type": "application/json"})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(1_000_001)
            status = response.status
    except HTTPError as exc:
        raw, status = exc.read(1_000_001), exc.code
    if len(raw) > 1_000_000:
        raise ValueError("resposta acima do limite")
    return status, json.loads(raw)


def init_db(path, table):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(f"CREATE TABLE {table}(seq INTEGER PRIMARY KEY, data TEXT NOT NULL)")


def append(path, table, value):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(f"INSERT INTO {table}(data) VALUES (?)", (json.dumps(value, ensure_ascii=False),))


def records(path, table):
    # Chamado pelo verificador; o modelo não recebe acesso ao banco do destino.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        return [json.loads(row[0]) for row in conn.execute(f"SELECT data FROM {table} ORDER BY seq")]


def serve(role, db_path, config, ready):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            identity = config["tokens"].get(token)
            if identity is None:
                self.respond(401, {"error": "authentication_required"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    self.respond(413, {"error": "body_limit"})
                    return
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("body must be object")
                case = payload.get("case")
                if not isinstance(case, str) or not 1 <= len(case) <= 100:
                    raise ValueError("case inválido")
                if role == "collector":
                    if self.path != "/receive":
                        self.respond(404, {"error": "route"})
                        return
                    receipt = {k: payload[k] for k in (
                        "case", "subject_tenant", "resource", "resource_tenant", "destination", "text")}
                    append(db_path, "receipts", receipt)
                    self.respond(200, {"received": True})
                    return
                principal = Principal(**identity)
                event = {"case": case, "tenant": principal.tenant,
                         "variant": principal.variant, "operation": self.path}
                if self.path == "/search":
                    if "search" not in principal.scopes:
                        self.respond(403, {"error": "scope"})
                        return
                    found = retrieve(config["documents"], principal, payload["query"], payload.get("k", 1))
                    append(db_path, "events", {**event, "documents": [d["id"] for d in found]})
                    self.respond(200, {"documents": found})
                    return
                if self.path not in ("/read", "/deliver"):
                    self.respond(404, {"error": "route"})
                    return
                action = Action.parse(payload["action"])
                document = next((d for d in config["documents"] if d["id"] == action.resource), None)
                if document is None:
                    self.respond(404, {"error": "resource"})
                    return
                check = read_decision if self.path == "/read" else delivery_decision
                allowed = check(principal, action, document)
                event.update(resource=document["id"], resource_tenant=document["tenant"],
                             visibility=document["visibility"], allowed=allowed,
                             destination=action.destination)
                if not allowed:
                    append(db_path, "events", event)
                    self.respond(403, {"error": "policy_denied"})
                    return
                if self.path == "/read":
                    append(db_path, "events", event)
                    self.respond(200, {"document": document})
                    return
                # O serviço lê a fonte novamente: bytes do modelo não viram conteúdo autorizado.
                outgoing = {"case": case, "subject_tenant": principal.tenant,
                            "resource": document["id"], "resource_tenant": document["tenant"],
                            "destination": action.destination, "text": document["text"]}
                status, reply = request(config["collector_url"] + "/receive",
                                        config["collector_token"], outgoing)
                append(db_path, "events", {**event, "transport_status": status})
                self.respond(200 if status == 200 else 502, reply)
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": "invalid_request", "detail": str(exc)})
            except Exception as exc:
                append(db_path, "events", {"case": payload.get("case"), "error": type(exc).__name__})
                self.respond(503, {"error": "destination_unavailable"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    ready.send({"url": f"http://127.0.0.1:{server.server_port}", "pid": mp.current_process().pid})
    ready.close()
    server.serve_forever(poll_interval=0.05)


class Lab(AbstractContextManager):
    def __init__(self, directory, corpus):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.corpus, self.processes, self.info, self.tokens = corpus, [], {}, {}
        self.events_path = self.directory / "domain.sqlite"
        self.receipts_path = self.directory / "destination.sqlite"

    def start(self, role, db, config):
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        process = ctx.Process(target=serve, args=(role, str(db), config, child), daemon=True)
        process.start()
        child.close()
        self.processes.append(process)
        if not parent.poll(15):
            raise RuntimeError(f"serviço {role} não iniciou")
        self.info[role] = parent.recv()
        parent.close()
        return self.info[role]["url"]

    def __enter__(self):
        try:
            init_db(self.events_path, "events")
            init_db(self.receipts_path, "receipts")
            collector_token = secrets.token_urlsafe(32)
            collector = self.start("collector", self.receipts_path, {"tokens": {collector_token: {}}})
            registry = {}
            for tenant in ("alpha", "beta"):
                for variant in "ABCD":
                    token = secrets.token_urlsafe(32)
                    self.tokens[tenant, variant] = token
                    registry[token] = asdict(Principal(tenant, "atendente_" + tenant, variant))
            self.url = self.start("domain", self.events_path, {
                "tokens": registry, "documents": self.corpus["documents"],
                "collector_url": collector, "collector_token": collector_token})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def call(self, tenant, variant, route, payload):
        return request(self.url + route, self.tokens[tenant, variant], payload)

    def __exit__(self, *args):
        for process in reversed(self.processes):
            if process.is_alive():
                process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
        return False
