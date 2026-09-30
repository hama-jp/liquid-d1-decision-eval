"""Offline reporting from immutable requests. Does not call any model API."""
import collections
import copy
import datetime
import hashlib
import json
import statistics
from pathlib import Path
from client import digest, validate
from history import read_attempts
from run_suite import score_record
import hard_stats

ROOT=Path(__file__).resolve().parent
LABELS={'policy':'例外付き規則','temporal':'移動・取消の状態追跡','schedule':'制約付き作業割当'}


def dump(path,value):
    (ROOT/path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def percent(v):
    return f'{100*v:.1f}%'


def main():
    hard_stats.main()
    hard=json.loads((ROOT/'hard-summary.json').read_text())
    hardcases=[json.loads(s) for s in (ROOT/'dataset/private-decisions-v5/items.jsonl').read_text().splitlines()]
    basic=json.loads((ROOT/'fixtures/basic.json').read_text())
    static=json.loads((ROOT/'fixtures/static.json').read_text())
    smoke=json.loads((ROOT/'fixtures/smoke.json').read_text())
    if isinstance(smoke,dict):smoke=[smoke]
    controls=json.loads((ROOT/'fixtures/hard-repeat.json').read_text())
    allcases=hardcases+basic+static+smoke+controls
    fmap={c['id']:c for c in allcases}
    attempts=read_attempts(ROOT);first={}
    for r in attempts:
        cid=r.get('case_id');c=fmap.get(cid)
        if c is None or r.get('request_sha256')!=digest(c['payload']):continue
        if r.get('http_status')==200 and cid not in first:first[cid]=copy.deepcopy(r)
    hardview=[]
    for c in hardcases+controls:
        r=first.get(c['id']);answer=None;correct=None;errors=[]
        if r:
            errors=validate(c['payload'],r.get('response'))
            if not errors:answer=r['response']['answers']['decision']
            correct=bool(answer and answer['choice']==c['gold_choice'])
        hardview.append({k:c[k] for k in ['id','family','difficulty','language','independent_item','payload','gold_choice','witness']} | {
            'variant':c.get('variant','canonical'),'base_id':c.get('base_id'), 'answer':answer,'correct':correct,
            'rtt_ms':r['rtt_ms'] if r else None,'contract_errors':errors})
    baseview=[]
    for c in basic:
        r=first.get(c['id'])
        if r is None and c['family']=='boundary':
            r=next((copy.deepcopy(x) for x in attempts if x.get('case_id')==c['id'] and x.get('request_sha256')==digest(c['payload']) and 400<=x.get('http_status',0)<500 and x.get('http_status')!=429),None)
        if r:score_record(c,r)
        baseview.append({'fixture':c,'result':r})
    staticview=[]
    for c in static:
        r=first.get(c['id'])
        if r:score_record(c,r)
        staticview.append({'fixture':c,'result':r})
    counts={}
    diagnostics={}
    for family,dest in [('basic',counts),('diagnostic',diagnostics)]:
        for key in ['problem','department','urgency']:
            rs=[r['result']['evaluation'][key] for r in baseview if r['fixture']['family']==family and r['result'] and key in r['result'].get('evaluation',{})]
            dest[key]={'correct':sum(x['correct'] for x in rs),'n':len(rs)}
    repeats=[]
    for c in controls:
        a=first.get(c['base_id']);b=first.get(c['id'])
        if not a or not b:continue
        assert a['request_sha256']==b['request_sha256']
        if validate(c['payload'],a['response']) or validate(c['payload'],b['response']):continue
        aa=a['response']['answers']['decision'];bb=b['response']['answers']['decision']
        deltas=[abs(aa['probabilities'][k]-bb['probabilities'][k]) for k in 'ABCD']
        repeats.append({'family':c['family'],'id':c['id'],'base_id':c['base_id'],
                        'flipped':aa['choice']!=bb['choice'],'max_probability_change':max(deltas),
                        'total_variation':sum(deltas)/2,'base_correct':aa['choice']==c['gold_choice'],
                        'repeat_correct':bb['choice']==c['gold_choice'],'identical_answer':aa==bb})
    repeat_summary=[{'family':fam,'n':sum(r['family']==fam for r in repeats),
                     'flips':sum(r['family']==fam and r['flipped'] for r in repeats),
                     'max_probability_change':max([r['max_probability_change'] for r in repeats if r['family']==fam] or [0])}
                    for fam in LABELS]
    canonical=[c for c in hardview if c['independent_item'] and c['answer']]
    confidence=[]
    for threshold in [.9,.95,.99]:
        subset=[c for c in canonical if c['answer']['probabilities'][c['answer']['choice']]>=threshold]
        confidence.append({'threshold':threshold,'n':len(subset),'errors':sum(not c['correct'] for c in subset)})
    static_summary={}
    for family in ['tactical','tactical_reverse','historical']:
        rs=[r['result'] for r in staticview if r['fixture']['family']==family and r['result']]
        static_summary[family]={'n':len(rs),'correct':sum(r.get('correct',False) for r in rs) if family!='historical' else None,
                                'same_as_historical_jev':sum(r.get('matches_historical_choice',False) for r in rs) if family=='historical' else None}
    ok=[r for r in attempts if r.get('http_status')==200]
    contracts=[{'id':r.get('case_id'),'errors':validate(r['request'],r.get('response'))} for r in ok]
    primary_hashes=json.loads((ROOT/'evidence/published-freeze-subset.json').read_text())['hashes']
    hash_checks={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected for name,expected in primary_hashes.items()}
    assert all(hash_checks.values()),'Frozen primary files changed'
    summary={'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'api_attempts':len(attempts),
             'http_statuses':dict(collections.Counter(str(r.get('http_status','timeout')) for r in attempts)),
             'transport_error_types':dict(collections.Counter(r.get('error','unknown') for r in attempts if not r.get('http_status'))),
             'http200':len(ok),'normal_contract_failures':[c for c in contracts if c['errors']],
             'models':sorted({r['response'].get('model','missing') for r in ok}),
             'usage':{'input_tokens':sum(r['response'].get('usage',{}).get('input_tokens',0) for r in ok),
                      'output_tokens':sum(r['response'].get('usage',{}).get('output_tokens',0) for r in ok),
                      'missing_usage':sum('usage' not in r['response'] for r in ok)},
             'rtt_reference':{'n':len(ok),'median_ms':statistics.median(r['rtt_ms'] for r in ok),
                              'p95_ms':sorted(r['rtt_ms'] for r in ok)[int(.95*(len(ok)-1))]},
             'basic':counts,'diagnostics':diagnostics,'static':static_summary,
             'repeat':repeat_summary,'repeat_completed':len(repeats),'repeat_planned':60,
             'confidence_subsets':confidence,'primary_frozen_hash_checks':hash_checks,
             'runs':[{**json.loads((p/'summary.json').read_text()),'name':p.name} for p in sorted((ROOT/'runs').iterdir()) if (p/'summary.json').exists()]}
    assert not summary['normal_contract_failures']
    assert len(ok)==766+len(repeats),'Unexpected duplicate or missing normal response'
    dump('final-summary.json',summary);dump('repeat-summary.json',{'summary':repeat_summary,'pairs':repeats})
    data={'summary':summary,'hard':hard,'cases':hardview,'basic':baseview,'static':staticview,'labels':LABELS}
    safe=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (ROOT/'viewer.html').write_text((ROOT/'final-viewer-template.html').read_text().replace('__DATA__',safe))
    print(json.dumps({'api_attempts':len(attempts),'http':summary['http_statuses'],'repeat':repeat_summary,'all_frozen_hashes_match':True},ensure_ascii=False))


if __name__=="__main__":main()
