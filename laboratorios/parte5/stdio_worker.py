"""Servidor MCP local: identidade fixada pelo lançador, sem OAuth HTTP."""
import os
from mcp.server import MCPServer


def main():
    principal = os.environ.get('LAB_PRINCIPAL')
    if principal not in ('alpha', 'beta'):
        raise SystemExit('LAB_PRINCIPAL explícito é obrigatório')
    server = MCPServer('L19 stdio', log_level='CRITICAL')

    @server.tool()
    def read_contract(resource: str) -> dict:
        """Contrato sintético do principal definido pelo processo pai."""
        allowed = resource == principal+'_contract'
        return {'allowed': allowed, 'text': 'STDIO_'+principal if allowed else None}

    server.run('stdio')


if __name__ == '__main__':
    main()
