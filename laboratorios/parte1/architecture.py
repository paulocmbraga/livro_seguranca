"""L02: caminhos finitos em um modelo explícito; não prova isolamento de SO."""
from pathlib import Path
from .common import create, material, read, write, seal, integrity, unique


def paths(graph, start, goal):
    nodes = unique(graph['nodes'])
    if start not in nodes or goal not in nodes:
        raise ValueError('Extremo desconhecido')
    adjacent = {n: [] for n in nodes}
    for edge in graph['edges']:
        if edge['from'] not in nodes or edge['to'] not in nodes:
            raise ValueError('Aresta sem nó')
        adjacent[edge['from']].append(edge['to'])
    result, stack = [], [(start, [start])]
    while stack:
        node, path = stack.pop()
        if node == goal:
            result.append(path)
        else:
            stack.extend((nxt, path + [nxt]) for nxt in adjacent[node] if nxt not in path)
    return sorted(result)


def assess(graph):
    nodes = unique(graph['nodes'])
    guard = graph['guard']
    if guard not in nodes or not graph['sources']:
        raise ValueError('Fronteira ausente')
    found = []
    for source in graph['sources']:
        routes = paths(graph, source, graph['effect'])
        if not routes:
            raise ValueError('Fonte desconectada: não confundir com defesa')
        found.extend(routes)
    bypass = [p for p in found if guard not in p]
    return {'id': graph['id'], 'guard': guard, 'paths': found, 'bypass': bypass,
            'mediates_all_modeled_paths': not bypass,
            'os_principals': sorted({n['os_principal'] for n in nodes.values()}),
            'claim': 'propriedade do grafo declarado, não prova de implantação'}


def run(out):
    root = create(out)
    data = material('arquiteturas.json')
    write(root / 'architectures.json', data)
    result = [assess(g) for g in data]
    write(root / 'results.json', result)
    seal(root, 'L02')
    return result


def verify(out):
    integrity(out, 'L02')
    root = Path(out)
    expected = [assess(g) for g in read(root / 'architectures.json')]
    if expected != read(root / 'results.json'):
        raise ValueError('Caminhos divergentes')
    return {'verified': True, 'architectures': len(expected)}
