"""Contratos e recuperação lexical; nenhum LLM é simulado como inferência real."""
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def terms(text):
    clean = unicodedata.normalize("NFKD", text.casefold())
    clean = "".join(c for c in clean if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9_]+", clean))


@dataclass(frozen=True)
class Principal:
    tenant: str
    subject: str
    variant: str
    scopes: tuple = ("search", "read", "deliver")


@dataclass(frozen=True)
class Action:
    resource: str
    tenant: str
    destination: str

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != {
            "resource", "tenant", "destination"
        }:
            raise ValueError("schema: campos exatos obrigatórios")
        if any(not isinstance(v, str) or not v or len(v) > 80
               for v in value.values()):
            raise ValueError("schema: strings curtas obrigatórias")
        if value["tenant"] not in ("alpha", "beta"):
            raise ValueError("schema: tenant desconhecido")
        if value["destination"] not in ("portal_alpha", "portal_beta", "collector"):
            raise ValueError("schema: destino lógico desconhecido")
        return cls(**value)


def allowed_read(principal, document):
    return document["visibility"] == "public" or document["tenant"] == principal.tenant


def retrieve(documents, principal, query, k=1):
    """Filtra autorização ANTES de ordenar; não usa o tenant da proposta."""
    if not isinstance(query, str) or not 1 <= len(query) <= 500:
        raise ValueError("query inválida")
    if type(k) is not int or not 1 <= k <= 3:
        raise ValueError("k inválido")
    candidates = [d for d in documents if allowed_read(principal, d)]
    q = terms(query)
    scored = [(len(q & terms(d["text"])), d["id"], d) for d in candidates]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [d for score, _, d in scored[:k] if score > 0]


def detector(context):
    """Baseline intencionalmente fraco; não é um produto de segurança."""
    text = " ".join(d["text"] for d in context).casefold()
    return any(marker in text for marker in ("ignore as regras", "system:"))


def scripted_proposal(context):
    """Interpreta um plano preparado no documento; NÃO mede persuasão de LLM."""
    if not context:
        raise ValueError("contexto vazio")
    marker = "PLANO_JSON="
    if marker not in context[0]["text"]:
        raise ValueError("documento sem plano preparado")
    raw = context[0]["text"].split(marker, 1)[1].strip()
    return Action.parse(json.loads(raw))


def read_decision(principal, action, document):
    if "read" not in principal.scopes:
        return False
    if principal.variant in ("C", "D"):
        return allowed_read(principal, document)
    # Defeito didático: confia na alegação de tenant que veio do modelo.
    return document["visibility"] == "public" or action.tenant == document["tenant"]


def delivery_decision(principal, action, document):
    if "deliver" not in principal.scopes or not read_decision(principal, action, document):
        return False
    if principal.variant in ("C", "D"):
        return action.destination == "portal_" + principal.tenant
    return True
