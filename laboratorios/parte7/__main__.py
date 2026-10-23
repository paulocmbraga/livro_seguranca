import argparse
import importlib
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', choices=['run', 'verify'])
    p.add_argument('lab', choices=['L25','L26','L27','L28'])
    p.add_argument('--out', required=True)
    a = p.parse_args()
    names = {'L25':'privacy','L26':'adaptation','L27':'deployment','L28':'release'}
    module = importlib.import_module('laboratorios.parte7.' + names[a.lab])
    print(json.dumps(getattr(module, a.operation)(a.out), ensure_ascii=False))


if __name__ == '__main__': main()
