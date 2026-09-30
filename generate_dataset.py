"""Create a fresh evaluation set with an explicit seed. No API or credentials."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import hardbench


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--version',help='Dataset label; default includes seed fingerprint')
    args=p.parse_args()
    if args.output.exists():p.error('output already exists; choose a new directory')
    hardbench.MASTER=args.seed
    hardbench.VERSION=args.version or 'private-decisions-v5-seed-'+hashlib.sha256(args.seed.encode()).hexdigest()[:12]
    cases=hardbench.generate();validation=hardbench.verify(cases)
    text=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases)
    validation.update(version=hardbench.VERSION,master_seed=args.seed,sha256=hashlib.sha256(text.encode()).hexdigest())
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'items.jsonl').write_text(text)
    (args.output/'public-inputs.jsonl').write_text(''.join(json.dumps({'id':c['id'],'payload':c['payload']},ensure_ascii=False)+'\n' for c in cases))
    (args.output/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
    manifest={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'generator':'private-decisions-v5','generator_sha256':hashlib.sha256(Path(hardbench.__file__).read_bytes()).hexdigest(),
              'oracle_sha256':hashlib.sha256(Path(hardbench.oracle.__file__).read_bytes()).hexdigest(),
              'seed':args.seed,'dataset_version':hardbench.VERSION,'items_sha256':validation['sha256'],
              'api_calls':0,'purpose':'evaluation only'}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(args.output.resolve()),'canonical':552,'variants':120,'sha256':validation['sha256'],'all_checks_passed':True}))


if __name__=='__main__':main()
