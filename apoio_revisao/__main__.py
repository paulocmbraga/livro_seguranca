import argparse
import json
from .privacidade import run, verify

def main():
    parser=argparse.ArgumentParser(description='L15 corrigido: conexões fechadas explicitamente')
    parser.add_argument('command',choices=['run','verify'])
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    print(json.dumps((run if args.command=='run' else verify)(args.out),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
