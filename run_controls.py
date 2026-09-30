"""Exploratory identical-input controls; never included in primary sample size."""
import argparse
import copy
import datetime
import hashlib
import json
import random
import time
from pathlib import Path
from client import Client, digest, validate
from history import read_attempts, terminal

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / 'fixtures' / 'hard-repeat.json'


def prepare():
    cases = [json.loads(s) for s in (ROOT/'dataset/private-decisions-v5/items.jsonl').read_text().splitlines()]
    controls = []
    for base in cases:
        if not base['independent_item'] or base['difficulty'] != 'hard' or int(base['id'].split('-')[-1]) >= 10:
            continue
        c = copy.deepcopy(base)
        c.update(id=base['id']+'-identical-repeat', base_id=base['id'], independent_item=False, variant='identical_repeat')
        controls.append(c)
    random.Random(2026093001).shuffle(controls)
    assert len(controls) == 60
    with FIXTURE.open('x') as f:
        f.write(json.dumps(controls, ensure_ascii=False, indent=2)+'\n')
    manifest = {'prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'count':len(controls), 'sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                'selection':'same prespecified 60 hard anchors as reverse/translation; no selection by outcome',
                'role':'exploratory paired control only; added after main study; excluded from all primary n/tests'}
    (ROOT/'evidence/repeat-frozen-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest))


def run(output, interval, timeout):
    cases = json.loads(FIXTURE.read_text())
    prior=read_attempts(ROOT)
    prior_attempts=sum(r.get('phase')=='hard_repeat' for r in prior)
    seen = {(r.get('case_id'), r.get('request_sha256') or digest(r['request'])) for r in prior if terminal(r)}
    todo = [c for c in cases if (c['id'],digest(c['payload'])) not in seen]
    out = ROOT/'runs'/output
    out.mkdir(exist_ok=False)
    config = {'phase':'hard_repeat', 'planned':60, 'todo':len(todo), 'parallelism':1, 'interval_seconds':interval,
              'timeout_seconds':timeout, 'max_attempts_per_item':3, 'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    attempts=0; done=0; reason='completed'; client=Client(timeout=timeout)
    with (out/'transport.jsonl').open('x') as raw, (out/'requests.jsonl').open('x') as scored:
        for c in todo:
            for attempt in range(1,4):
                if prior_attempts+attempts>=180:
                    reason='total_control_attempt_budget_reached';break
                if attempts: time.sleep(interval)
                r=client.call(c['payload']); attempts+=1
                r.update(case_id=c['id'],base_id=c['base_id'],family=c['family'],phase='hard_repeat',
                         independent_item=False,attempt_for_item=attempt,retry=attempt>1)
                raw.write(json.dumps(r,ensure_ascii=False)+'\n');raw.flush()
                status=r.get('http_status',0)
                if status==200:
                    r['contract_errors']=validate(c['payload'],r.get('response'))
                    if not r['contract_errors']:
                        a=r['response']['answers']['decision']
                        r.update(choice=a['choice'],gold_choice=c['gold_choice'],correct=a['choice']==c['gold_choice'])
                scored.write(json.dumps(r,ensure_ascii=False)+'\n');scored.flush()
                if not status or status==429 or status>=500:
                    print(json.dumps({'case':c['id'],'attempt':attempt,'http':status,'error':r.get('error')}),flush=True)
                    if attempt==3:reason='service_failure_three_attempts';break
                    try:delay=min(60,max(float(r.get('response_headers',{}).get('retry-after') or 0),3*2**(attempt-1)))
                    except ValueError:delay=3*2**(attempt-1)
                    time.sleep(delay);continue
                if status!=200 or r.get('contract_errors'):
                    reason='http_or_contract_error';break
                done+=1
                if done%10==0 or done==1 or done==len(todo):
                    print(json.dumps({'completed':done,'remaining':len(todo)-done,'attempts':attempts}),flush=True)
                break
            if reason!='completed':break
    client.close()
    result={**config,'completed':done,'attempts':attempts,'reason':reason,'ended_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return 0 if reason=='completed' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--output',default='repeat-001');p.add_argument('--interval',type=float,default=1);p.add_argument('--timeout',type=float,default=30)
    a=p.parse_args()
    if a.prepare: prepare()
    else:
        if a.interval<1:p.error('interval must be at least 1 second')
        if not 30<=a.timeout<=120:p.error('timeout must be between 30 and 120 seconds')
        raise SystemExit(run(a.output,a.interval,a.timeout))
