import argparse
import importlib
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['run', 'verify'])
    p.add_argument('lab', choices=['L29', 'L30', 'L31', 'L32'])
    p.add_argument('--out', required=True)
    a = p.parse_args()
    name = {'L29':'campaign','L30':'evaluation','L31':'telemetry','L32':'incident'}[a.lab]
    module = importlib.import_module('laboratorios.parte8.'+name)
    print(json.dumps(getattr(module, a.operation)(a.out), ensure_ascii=False))


if __name__ == '__main__':
    main()
