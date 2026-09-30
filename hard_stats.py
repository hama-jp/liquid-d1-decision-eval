"""Prespecified exact tests, confidence intervals and paired robustness analysis."""
import collections
import json
import math
from pathlib import Path
from client import digest, validate
from history import read_attempts

ROOT=Path(__file__).resolve().parent


def binomial_upper(k,n,p=.25):
    return min(1.0,sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(k,n+1)))


def wilson(k,n):
    if not n:return None
    z=1.959963984540054;p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,mid-half),min(1,mid+half)]


def holm(ps):
    result={};running=0
    for i,(key,p) in enumerate(sorted(ps.items(),key=lambda kv:kv[1])):
        running=max(running,min(1,(len(ps)-i)*p));result[key]=running
    return result


def main():
    fixtures=[json.loads(s) for s in (ROOT/'dataset'/'private-decisions-v5'/'items.jsonl').read_text().splitlines()]
    fmap={f['id']:f for f in fixtures}
    expected_hashes={f['id']:digest(f['payload']) for f in fixtures}
    records={};attempts=[]
    for r in read_attempts(ROOT):
        if r.get('phase')!='hard':continue
        if r.get('request_sha256')!=expected_hashes.get(r.get('case_id')):continue
        attempts.append(r)
        if r.get('http_status')!=200 or r['case_id'] in records:continue
        case=fmap[r['case_id']]
        errors=validate(case['payload'],r.get('response'))
        r.update(contract_errors=errors,correct=False,p_gold=None,brier=None,choice_probability=None,choice=None,gold_choice=case['gold_choice'])
        if not errors:
            a=r['response']['answers']['decision'];gold=case['gold_choice']
            r.update(choice=a['choice'],correct=a['choice']==gold,p_gold=a['probabilities'][gold],
                     choice_probability=a['probabilities'][a['choice']],brier=sum((p-int(k==gold))**2 for k,p in a['probabilities'].items()))
        records[r['case_id']]=r
    rows=[]
    for family in ['policy','temporal','schedule']:
        for difficulty in ['easy','medium','hard']:
            for language in ['all','en','ja']:
                cases=[f for f in fixtures if f['independent_item'] and f['family']==family and f['difficulty']==difficulty and (language=='all' or f['language']==language)]
                got=[records[f['id']] for f in cases if f['id'] in records];k=sum(r['correct'] for r in got);n=len(got)
                rows.append({'family':family,'difficulty':difficulty,'language':language,'planned':len(cases),'n':n,'correct':k,
                             'accuracy':k/n if n else None,'wilson_95':wilson(k,n),'binomial_p_one_sided':binomial_upper(k,n) if n==len(cases) else None,
                             'mean_p_gold':sum(r['p_gold'] for r in got if r['p_gold'] is not None)/sum(r['p_gold'] is not None for r in got) if any(r['p_gold'] is not None for r in got) else None,
                             'mean_brier':sum(r['brier'] for r in got if r['brier'] is not None)/sum(r['brier'] is not None for r in got) if any(r['brier'] is not None for r in got) else None})
    primary=[r for r in rows if r['difficulty']=='hard' and r['language']=='all']
    if all(r['n']==r['planned'] for r in primary):
        adj=holm({r['family']:r['binomial_p_one_sided'] for r in primary})
        for row in primary:row['holm_adjusted_p']=adj[row['family']];row['above_chance_familywise_05']=adj[row['family']]<.05
    variants=[]
    for f in fixtures:
        if f['independent_item'] or f['id'] not in records or f['base_id'] not in records:continue
        a,b=records[f['base_id']],records[f['id']]
        base=fmap[f['base_id']]
        ai=base['option_internal_order'][ord(a['choice'])-65] if a['choice'] else None
        bi=f['option_internal_order'][ord(b['choice'])-65] if b['choice'] else None
        variants.append({'family':f['family'],'variant':f['variant'],'base_id':f['base_id'],'case_id':f['id'],
                         'base_correct':a['correct'],'variant_correct':b['correct'],'choice_flipped':ai!=bi,
                         'absolute_p_gold_change':abs(a['p_gold']-b['p_gold']) if a['p_gold'] is not None and b['p_gold'] is not None else None})
    variant_summary=[]
    for family in ['policy','temporal','schedule']:
        for variant in ['reverse','translation']:
            rs=[r for r in variants if r['family']==family and r['variant']==variant]
            variant_summary.append({'family':family,'variant':variant,'n':len(rs),'flips':sum(r['choice_flipped'] for r in rs),
                                    'correct_to_wrong':sum(r['base_correct'] and not r['variant_correct'] for r in rs),
                                    'wrong_to_correct':sum(not r['base_correct'] and r['variant_correct'] for r in rs)})
    confident_wrong=sorted([{'id':key,'family':r['family'],'probability':r['choice_probability'],'gold':r['gold_choice'],'choice':r['choice']} for key,r in records.items() if not r['correct'] and r['choice_probability'] is not None],key=lambda r:r['probability'],reverse=True)
    report={'canonical_completed':sum(f['independent_item'] and f['id'] in records for f in fixtures),'canonical_planned':552,
            'variants_completed':len(variants),'variants_planned':120,'transport_attempts':len(attempts),
            'transport_statuses':dict(collections.Counter(str(r.get('http_status')) for r in attempts)),
            'invalid_200_count':sum(bool(r.get('contract_errors')) for r in records.values()),
            'primary':primary,'all_cells':rows,'robustness':variant_summary,'paired_details':variants,
            'confident_errors':confident_wrong[:30],'notes':'Only first HTTP 200 responses scored; exact one-sided binomial against 25%; Holm across the three hard-family tests. Variants excluded from independent denominators.'}
    (ROOT/'hard-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['paired_details','all_cells','confident_errors']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
