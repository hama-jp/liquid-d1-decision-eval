"""Run only frozen fixtures. Serial, no retries, all responses retained."""
import argparse
import json
import time
from pathlib import Path
from client import Client, validate, evaluate

ROOT=Path(__file__).resolve().parent


def score_record(case, rec):
    if case['family']=='boundary':
        return
    if rec.get('http_status')!=200:
        return
    errors=validate(case['payload'],rec.get('response'))
    rec['contract_errors']=errors
    if errors:return
    answers=rec['response']['answers']
    if case.get('gold') is not None:
        rec['evaluation']=evaluate(answers,case['gold'],case.get('key_map'))
    if 'move' in answers:
        a=answers['move'];choice=a['choice'];selected=case['payload']['questions']['move']['criteria'][choice]
        rec['selected_option']=selected
        if case.get('gold_choices') is not None:
            rec['correct']=choice in case['gold_choices']
            rec['p_gold']=sum(a['probabilities'][k] for k in case['gold_choices'])
        if 'historical_answer' in case:
            rec['matches_historical_choice']=choice==case['historical_answer']['choice']


def main(args):
    cases=json.loads((ROOT/'fixtures'/f'{args.suite}.json').read_text())
    if isinstance(cases,dict):cases=[cases]
    cases=cases[args.offset:]
    out=ROOT/'runs'/args.output
    out.mkdir(parents=True,exist_ok=False)
    client=Client();records=[];reason='completed'
    with (out/'requests.jsonl').open('x') as log:
        for case in cases:
            if records and args.interval:
                time.sleep(args.interval)
            rec=client.call(case['payload']);rec['case_id']=case['id'];rec['family']=case['family']
            try:
                score_record(case,rec)
            except Exception as error:
                rec['scoring_error']=type(error).__name__
            if case['family']=='boundary':rec['expected_rejection']=400<=rec.get('http_status',0)<500 and rec.get('http_status') not in [401,403,429]
            log.write(json.dumps(rec,ensure_ascii=False)+'\n');log.flush();records.append(rec)
            print(json.dumps({'case':case['id'],'http':rec.get('http_status'),'rtt_ms':round(rec['rtt_ms']),
                  'contract_errors':rec.get('contract_errors'), 'evaluation':rec.get('evaluation'),
                  'correct':rec.get('correct')},ensure_ascii=False),flush=True)
            status=rec.get('http_status',0)
            if not status or status in [401,403,429] or status>=500:
                reason='service_error';break
            if status!=200 and case['family']!='boundary':
                reason='unexpected_http_error';break
    client.close()
    summary={'suite':args.suite,'planned':len(cases),'attempted':len(records),'reason':reason,
             'http_statuses':{str(code):sum(r.get('http_status')==code for r in records) for code in {r.get('http_status') for r in records}},
             'contract_failures':sum(bool(r.get('contract_errors')) for r in records)}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 0 if reason=='completed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('suite',choices=['smoke','basic','static']);p.add_argument('--output',required=True)
    p.add_argument('--offset',type=int,default=0);p.add_argument('--interval',type=float,default=0)
    raise SystemExit(main(p.parse_args()))
