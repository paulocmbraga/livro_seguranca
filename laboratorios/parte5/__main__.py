import argparse
import importlib
import json

def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['run','verify'])
    p.add_argument('lab',choices=['L17','L18','L19','L20']);p.add_argument('--out',required=True)
    a=p.parse_args();names={'L17':'actions','L18':'delegation','L19':'mcp_lab','L20':'a2a_lab'}
    module=importlib.import_module('laboratorios.parte5.'+names[a.lab])
    result=getattr(module,a.operation)(a.out)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
