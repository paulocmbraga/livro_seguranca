import argparse
import importlib
import json


def main():
    p=argparse.ArgumentParser()
    p.add_argument('operation',choices=['run','verify'])
    p.add_argument('lab',choices=['L33','L34','L35','L36'])
    p.add_argument('--out',required=True)
    p.add_argument('--cache')
    args=p.parse_args()
    name={'L33':'assurance','L34':'ml_case','L35':'knowledge','L36':'operations'}[args.lab]
    module=importlib.import_module('laboratorios.parte9.'+name)
    extra={'cache':args.cache} if args.lab=='L35' and args.operation=='run' else {}
    print(json.dumps(getattr(module,args.operation)(args.out,**extra),ensure_ascii=False))


if __name__=='__main__': main()
