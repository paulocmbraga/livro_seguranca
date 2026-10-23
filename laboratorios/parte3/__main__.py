import argparse
import json
from . import retrieval,memory,rag,transforms

p=argparse.ArgumentParser()
p.add_argument('operation',choices=['run','verify'])
p.add_argument('lab',choices=['L09','L10','L11','L12'])
p.add_argument('--out',required=True)
p.add_argument('--cache')
p.add_argument('--config',choices=['q4_k_m','q8_0'],default='q4_k_m')
p.add_argument('--ocr-image',default='livro-seguranca-ocr:parte3-v1')
p.add_argument('--closed-resources',action='store_true')
a=p.parse_args()
module={'L09':rag,'L10':retrieval,'L11':transforms,'L12':memory}[a.lab]
if a.operation=='verify': result=module.verify(a.out)
elif a.lab in ('L09','L11'):
    if not a.cache: p.error('--cache é obrigatório para inferência real')
    result=(module.run(a.out,a.cache,a.config,a.closed_resources) if a.lab=='L09'
            else module.run(a.out,a.cache,a.ocr_image))
else: result=module.run(a.out)
print(json.dumps(result,ensure_ascii=False))
