"""Paced, resumable evaluation. Only transient service failures may be resent.

All attempts are journaled before scoring. The first HTTP 200 per item is
the outcome, regardless of whether it is correct or confident. No answer-based retry.
"""
import argparse
import datetime
import json
import time
from pathlib import Path
from client import Client, validate, digest
from run_suite import score_record
from history import read_attempts, terminal

ROOT=Path(__file__).resolve().parent


def previous_successes():
    result=set()
    for r in read_attempts(ROOT):
        if terminal(r) and r.get('case_id'):
            result.add((r['case_id'],r.get('request_sha256') or digest(r['request'])))
    return result


def main(args):
    if args.suite=='hard':
        cases=[json.loads(line) for line in (ROOT/'dataset'/'private-decisions-v5'/'items.jsonl').read_text().splitlines()]
    else:
        cases=json.loads((ROOT/'fixtures'/f'{args.suite}.json').read_text())
    completed=previous_successes();todo=[c for c in cases if (c['id'],digest(c['payload'])) not in completed]
    out=ROOT/'runs'/args.output;out.mkdir(parents=True,exist_ok=False)
    client=Client(timeout=30);attempts=0;done=0;reason='completed';results=[]
    config={'suite':args.suite,'planned_items':len(cases),'previously_completed':len(cases)-len(todo),
            'todo':len(todo),'interval_after_response_seconds':args.interval,'request_timeout_seconds':30,
            'max_attempts_per_item':3,'parallelism':1,'score_policy':'first HTTP200 only; never retry a model error',
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    with (out/'transport.jsonl').open('x') as raw,(out/'requests.jsonl').open('x') as log:
        for case in todo:
            for attempt in range(1,4):
                if attempts:time.sleep(args.interval)
                rec=client.call(case['payload']);attempts+=1
                rec.update(case_id=case['id'],family=case['family'],attempt_for_item=attempt,
                           retry=attempt>1,phase=args.suite)
                if args.suite=='hard':rec.update(difficulty=case['difficulty'],language=case['language'],independent_item=case['independent_item'],dataset_version=case['version'])
                # Save the complete transport result first, even if the scorer fails.
                raw.write(json.dumps(rec,ensure_ascii=False)+'\n');raw.flush()
                status=rec.get('http_status',0)
                try:
                    if args.suite=='hard' and status==200:
                        rec['contract_errors']=validate(case['payload'],rec.get('response'))
                        if not rec['contract_errors']:
                            a=rec['response']['answers']['decision'];gold=case['gold_choice']
                            rec.update(choice=a['choice'],gold_choice=gold,correct=a['choice']==gold,p_gold=a['probabilities'][gold],
                                       choice_probability=a['probabilities'][a['choice']],
                                       brier=sum((p-int(k==gold))**2 for k,p in a['probabilities'].items()))
                    elif args.suite!='hard':score_record(case,rec)
                    if case['family']=='boundary':rec['expected_rejection']=400<=status<500 and status not in [401,403,429]
                except Exception as error:rec['scoring_error']=type(error).__name__
                log.write(json.dumps(rec,ensure_ascii=False)+'\n');log.flush();results.append(rec)
                transient=not status or status==429 or status>=500
                if transient:
                    print(json.dumps({'case':case['id'],'attempt':attempt,'http':status,'error':rec.get('error'),'rtt_ms':round(rec['rtt_ms']),'service_failure':True}),flush=True)
                    if attempt==3:reason='service_failure_three_attempts';break
                    retry=rec.get('response_headers',{}).get('retry-after')
                    try:backoff=min(60,max(float(retry or 0),3*(2**(attempt-1))))
                    except ValueError:backoff=3*(2**(attempt-1))
                    time.sleep(backoff)
                    continue
                if status!=200 and not (case['family']=='boundary' and rec.get('expected_rejection')):
                    reason='unexpected_http_error';break
                if rec.get('contract_errors') or rec.get('scoring_error'):
                    reason='contract_or_scoring_error';break
                done+=1
                if done%10==0 or done==1 or done==len(todo):
                    print(json.dumps({'suite':args.suite,'completed':done,'remaining':len(todo)-done,'attempts':attempts,
                                      'case':case['id'],'rtt_ms':round(rec['rtt_ms']),'correct':rec.get('correct')}),flush=True)
                break
            if reason!='completed':break
    client.close()
    summary={**config,'completed_in_run':done,'attempts':attempts,'reason':reason,'ended_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if reason=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('suite',choices=['basic','static','hard']);p.add_argument('--output',required=True);p.add_argument('--interval',type=float,default=1)
    raise SystemExit(main(p.parse_args()))
