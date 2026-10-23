import argparse
import json
from . import access_labs, supply, isolation

p = argparse.ArgumentParser()
p.add_argument('action', choices=['run', 'verify'])
p.add_argument('lab', choices=['L05', 'L06', 'L07', 'L08'])
p.add_argument('--out', required=True)
args = p.parse_args()
if args.lab in ('L05', 'L06'):
    result = (getattr(access_labs, args.lab.lower())(args.out) if args.action == 'run'
              else access_labs.verify_access(args.out, args.lab))
else:
    module = supply if args.lab == 'L07' else isolation
    result = getattr(module, args.action)(args.out)
print(json.dumps(result, ensure_ascii=False))
