"""Recalcula oráculos da captura; um passed gravado não é tomado como prova."""
import argparse
import json
from pathlib import Path
from .common import verify
from laboratorios.l09.campaign import verify as verify_rag


def run(directory):
    root = Path(directory)
    result = verify(root)
    report = json.loads((root/'results.json').read_text(encoding='utf-8'))
    if report['version'] == 'M1-L09-1.0':
        result['rag'] = verify_rag(root)
        ledger = json.loads((root/'inference_ledger.json').read_text(encoding='utf-8'))
        if report['inference_calls'] != len(ledger) or len(ledger) != 20:
            raise ValueError('Cardinalidade de inferências divergente')
        keys = {item['prompt_sha256'] for item in ledger}
        if len(keys) != len(ledger) or any(not item['real_inference'] for item in ledger):
            raise ValueError('Ledger de inferência inconsistente')
        result['inference_calls'] = len(ledger)
    else:
        checks = report['checks']
        if len({c['name'] for c in checks}) != 29 or len(checks) != 29 or not all(c['passed'] for c in checks):
            raise ValueError('Campanha de protocolos incompleta ou com falhas')
        events = json.loads((root/'server_events.json').read_text(encoding='utf-8'))
        reads = [e for e in events['mcp'] if e['operation'] == 'read_contract']
        if len(reads) != 4 or sum(e['allowed'] for e in reads) != 2:
            raise ValueError('Oráculo MCP não corresponde aos quatro acessos esperados')
        if any(e['allowed'] and e['resource'] != e['subject']+'_contract' for e in reads):
            raise ValueError('Leitura cruzada permitida')
        created = [e for e in events['a2a'] if e['operation'] == 'created']
        canceled = [e for e in events['a2a'] if e['operation'] == 'canceled']
        denied = [e for e in events['a2a'] if e['operation'] in ('task_access', 'context_access') and not e['allowed']]
        if len(created) != 2 or len(canceled) != 1 or len(denied) != 3:
            raise ValueError('Oráculo A2A diverge das tarefas e recusas esperadas')
        result.update(checks=29, mcp_reads=len(reads), a2a_created=len(created), a2a_denied=len(denied))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False))
