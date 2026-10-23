import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys


def diagnose():
    packages = {}
    for name in ('mcp', 'a2a-sdk', 'PyJWT', 'psutil', 'httpx', 'httpx2', 'uvicorn'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    result = {'python': platform.python_version(), 'system': platform.system(),
              'architecture': platform.machine(), 'packages': packages,
              'disk_free_bytes': shutil.disk_usage(Path.cwd()).free,
              'core_python_qualified_version': sys.version_info[:2] == (3, 12),
              'extensions_installed': all(packages.values()),
              'inference_executed_by_this_diagnostic': False,
              'ports_exposed_by_this_diagnostic': False}
    try:
        import psutil
        result.update(ram_total_bytes=psutil.virtual_memory().total,
                      ram_available_bytes=psutil.virtual_memory().available,
                      cpu_logical=psutil.cpu_count(), cpu_physical=psutil.cpu_count(logical=False))
    except ImportError:
        result['resources_note'] = 'psutil opcional ausente; recursos não medidos'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out')
    args = parser.parse_args()
    report = diagnose()
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
