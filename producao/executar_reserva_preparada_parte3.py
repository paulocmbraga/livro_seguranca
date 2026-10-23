"""Entrada em arquivo para o spawn de processos no Windows."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from laboratorios.l09 import campaign


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',required=True)
    args=parser.parse_args()
    corpus=json.loads((PROJECT/'materiais/parte3/rag_reserva.json').read_text(encoding='utf-8'))
    with patch.object(campaign,'make_corpus',return_value=corpus):
        campaign.run(args.out,split='eval')
    print(json.dumps(campaign.verify(args.out),ensure_ascii=False))


if __name__=='__main__': main()
