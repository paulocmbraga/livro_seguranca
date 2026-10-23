import argparse
import importlib
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['run', 'verify'])
    p.add_argument('lab', choices=['L21', 'L22', 'L23', 'L24'])
    p.add_argument('--out', required=True)
    a = p.parse_args()
    names = {'L21': 'pipeline', 'L22': 'poisoning', 'L23': 'evasion', 'L24': 'extraction'}
    module = importlib.import_module('laboratorios.parte6.' + names[a.lab])
    print(json.dumps(getattr(module, a.operation)(a.out), ensure_ascii=False))


if __name__ == '__main__':
    main()
