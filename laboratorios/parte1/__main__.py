"""python -m laboratorios.parte1 run L01 --out output/minha_execucao/l01"""
import argparse
import json
from . import requirements, architecture, controls, observatory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'verify'))
    parser.add_argument('lab', choices=('L01', 'L02', 'L03', 'L04'))
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    module = dict(L01=requirements, L02=architecture, L03=controls, L04=observatory)[args.lab]
    print(json.dumps(getattr(module, args.command)(args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
