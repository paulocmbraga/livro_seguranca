import argparse
import importlib
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['run', 'verify'])
    p.add_argument('lab', choices=['L13', 'L14', 'L15', 'L16'])
    p.add_argument('--out', required=True)
    p.add_argument('--browser', help='Executável Edge/Chromium local; somente L14')
    a = p.parse_args()
    module = importlib.import_module('laboratorios.parte4.' + {
        'L13': 'guardrails', 'L14': 'consumers', 'L15': 'privacy', 'L16': 'budget'}[a.lab])
    if a.operation == 'verify':
        result = module.verify(a.out)
    elif a.lab == 'L14':
        result = module.run(a.out, a.browser)
    else:
        result = module.run(a.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
