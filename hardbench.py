"""Reusable new-item decision benchmark. No model, network, or LLM gold labels."""
import argparse
import collections
import copy
import hashlib
import json
import random
from pathlib import Path
import hard_oracle as oracle
from client import MODEL, digest

ROOT=Path(__file__).resolve().parent
VERSION='private-decisions-v5'
MASTER='liquid-private-decisions-20260930-a7e4169f'
COUNTS={'easy':32,'medium':32,'hard':120}
FIELDS={'error_percent':100,'healthy_replicas':8,'backup_age_hours':72,'open_incidents':6,'approved':1,'security_alert':1}
FIELD_NOTES={
 'en':'error_percent: failed requests (%); healthy_replicas: working replicas; backup_age_hours: time since backup; open_incidents: active incidents; approved/security_alert: 1=true, 0=false.',
 'ja':'error_percent: エラー率（%）、healthy_replicas: 正常なレプリカ数、backup_age_hours: バックアップからの時間、open_incidents: 未解決障害数、approved/security_alert: 1が真、0が偽。'}
ACTIONS={'en':['Release to all users','Release to a small canary group','Hold the release','Roll back the release'],
         'ja':['全利用者へ公開する','小規模なカナリア群へ公開する','公開を保留する','公開をロールバックする']}


def seeded(*parts):
    return random.Random(int(hashlib.sha256((MASTER+'|'+ '|'.join(map(str,parts))).encode()).hexdigest(),16))


def expr_value(expr,facts):
    if expr['kind']=='atom':
        a,b=facts[expr['field']],expr['value']
        return {'ge':a>=b,'lt':a<b,'eq':a==b}[expr['op']]
    values=[expr_value(c,facts) for c in expr['children']]
    return all(values) if expr['kind']=='all' else any(values)


def expression(rng,facts,arity,wanted):
    for _ in range(10000):
        children=[]
        for field in rng.sample(list(FIELDS),arity):
            children.append({'kind':'atom','field':field,'op':rng.choice(['ge','lt']) if FIELDS[field]>1 else 'eq',
                             'value':rng.randint(1,FIELDS[field]) if FIELDS[field]>1 else rng.randrange(2)})
        expr=children[0] if arity==1 else {'kind':rng.choice(['all','any']),'children':children}
        if expr_value(expr,facts)==wanted:return expr
    raise AssertionError('expression construction failed')


def expr_text(expr,language):
    if expr['kind']=='atom':
        op={'ge':'>=','lt':'<','eq':'='}[expr['op']]
        return f"{expr['field']} {op} {expr['value']}"
    join={'en':{'all':' AND ','any':' OR '},'ja':{'all':' かつ ','any':' または '}}[language][expr['kind']]
    return '('+join.join(expr_text(c,language) for c in expr['children'])+')'


def policy(rng,difficulty):
    n={'easy':4,'medium':6,'hard':10}[difficulty];arity={'easy':1,'medium':2,'hard':3}[difficulty]
    facts={k:rng.randint(0,maximum) for k,maximum in FIELDS.items()}
    priorities=rng.sample(range(10,100),n);rules=[]
    # Random policy, conditioned on needing both precedence and an exception.
    for _ in range(1000):
        rules=[]
        rule_ids=rng.sample(range(1000,10000),n)
        for i,p in enumerate(priorities):
            rules.append({'id':f'R{rule_ids[i]}','priority':p,
                          'when':expression(rng,facts,arity,rng.random()<.75),
                          'except':expression(rng,facts,arity,rng.random()<.45),'action':rng.randrange(4)})
        applicable=[r for r in rules if expr_value(r['when'],facts) and not expr_value(r['except'],facts)]
        if len(applicable)<2:continue
        winner=max(applicable,key=lambda r:r['priority'])
        naive=max([r for r in rules if expr_value(r['when'],facts)],key=lambda r:r['priority'])
        if difficulty=='hard' and (winner['action']==naive['action'] or winner['priority']==naive['priority']):continue
        if len({r['action'] for r in applicable})<2:continue
        break
    else:raise AssertionError('no policy')
    rng.shuffle(rules)
    data={'facts':facts,'rules':rules,'default':rng.randrange(4)}
    gold=winner['action'];assert oracle.policy_answer(data)==gold
    witness={'winning_rule':winner['id'],'checks':[{'id':r['id'],'condition':expr_value(r['when'],facts),
             'exception':expr_value(r['except'],facts),'priority':r['priority'],'action':r['action']} for r in rules]}
    return data,gold,witness


def temporal(rng,difficulty):
    n={'easy':4,'medium':8,'hard':8}[difficulty];m={'easy':5,'medium':12,'hard':22}[difficulty]
    minimum={'easy':1,'medium':2,'hard':4}[difficulty]
    names=rng.sample(['Aster','Birch','Cedar','Dahlia','Elm','Fern','Ginkgo','Hazel','Iris','Juniper','Larch','Maple'],n)
    places=rng.sample(['North','South','East','West'],4)
    for _ in range(2000):
        starting_places=places*(n//4);rng.shuffle(starting_places)
        initial=dict(zip(names,starting_places))
        minutes=sorted(rng.sample(range(480,1020),m));events=[]
        event_ids=rng.sample(range(100,1000),m)
        for i,minute in enumerate(minutes):
            if rng.random()<(.95 if difficulty=='hard' else .8):
                events.append({'id':f'E{event_ids[i]}','minute':minute,'kind':'swap','items':rng.sample(names,2)})
            else:
                events.append({'id':f'E{event_ids[i]}','minute':minute,'kind':'move','item':rng.choice(names),'location':rng.choice(places)})
        cancelled=rng.sample([e['id'] for e in events],{'easy':0,'medium':2,'hard':4}[difficulty])
        states=dict(initial);uncancelled=dict(initial)
        for event in events:
            def update(s):
                if event['kind']=='move':s[event['item']]=event['location']
                else:
                    a,b=event['items'];s[a],s[b]=s[b],s[a]
            update(uncancelled)
            if event['id'] not in cancelled:update(states)
        target=rng.choice(names)
        data={'initial':initial,'events':events,'cancelled':cancelled,'target':target,'locations':places}
        reference,trace=oracle.temporal_answer(data)
        assert reference==states[target]
        if len(trace)<minimum:continue
        if difficulty=='hard' and uncancelled[target]==states[target]:continue
        rng.shuffle(data['events'])
        return data,states[target],{'backward_trace':trace,'final_locations':states,'ignoring_cancellations':uncancelled[target]}
    raise AssertionError('temporal task construction failed')


def violations(data,plan):
    result=[]
    for job,req in data['requirements'].items():
        if plan[job]['worker'] not in req['workers']:result.append(('worker',job))
        if plan[job]['slot'] not in req['slots']:result.append(('slot',job))
    jobs=sorted(plan)
    for i,a in enumerate(jobs):
        for b in jobs[i+1:]:
            if plan[a]==plan[b]:result.append(('collision',a,b))
    for a,b in data['precedes']:
        if plan[a]['slot']>=plan[b]['slot']:result.append(('precedence',a,b))
    return sorted(result)


def schedule(rng,difficulty):
    n={'easy':3,'medium':5,'hard':7}[difficulty]
    workers=rng.sample(['Aki','Bea','Cai','Dora','Emi','Finn','Gus','Hana'],4)
    jobs=rng.sample(['Aster','Birch','Cedar','Dahlia','Elm','Fern','Ginkgo','Hazel','Iris','Juniper'],n)
    # Generate four proposals BEFORE choosing which one is correct. Require a
    # symmetric property: every proposal has a condition that can exclude only
    # that proposal. Then choose the correct one uniformly and write the rules.
    # Thus candidate-only statistics cannot reveal the target by construction.
    for _ in range(2000):
        plans=[]
        for _ in range(4):
            cells=rng.sample([(w,t) for w in workers for t in [1,2,3]],n)
            plans.append({j:{'worker':w,'slot':t} for j,(w,t) in zip(jobs,cells)})
        if len({digest(p) for p in plans})<4:continue
        pool=[[] for _ in range(4)]
        neutral=[]
        for job in jobs:
            for field,values in [('worker',workers),('slot',[1,2,3])]:
                for value in values:
                    bad=[i for i,p in enumerate(plans) if p[job][field]==value]
                    restriction=('exclude',job,field,value)
                    if len(bad)==1:pool[bad[0]].append(restriction)
                    elif not bad:neutral.append(restriction)
        for a in jobs:
            for b in jobs:
                if a==b:continue
                bad=[i for i,p in enumerate(plans) if p[a]['slot']>=p[b]['slot']]
                restriction=('precedes',a,b)
                if len(bad)==1:pool[bad[0]].append(restriction)
                elif not bad:neutral.append(restriction)
        if all(pool):break
    else:raise AssertionError('symmetric proposal construction failed')
    gold=rng.randrange(4)
    requirements={j:{'workers':list(workers),'slots':[1,2,3]} for j in jobs}
    precedes=[];chosen=[]
    for i in range(4):
        if i!=gold:chosen.append(rng.choice(pool[i]))
    rng.shuffle(neutral)
    chosen+=neutral[:{'easy':0,'medium':3,'hard':6}[difficulty]]
    for rule in chosen:
        if rule[0]=='exclude':
            _,job,field,value=rule
            key='workers' if field=='worker' else 'slots'
            if value in requirements[job][key]:requirements[job][key].remove(value)
        else:precedes.append((rule[1],rule[2]))
    for req in requirements.values():
        rng.shuffle(req['workers']);rng.shuffle(req['slots'])
    rng.shuffle(precedes)
    data={'workers':workers,'requirements':requirements,'precedes':precedes,'plans':plans}
    for p in plans:assert violations(data,p)==oracle.schedule_violations(data,p)
    valid=[i for i,p in enumerate(plans) if not violations(data,p)]
    assert valid==[gold]
    assert all(len(violations(data,p))==1 for i,p in enumerate(plans) if i!=gold)
    return data,gold,{'candidate_violations':[violations(data,p) for p in plans],
                     'construction':'exchangeable proposals; target uniform after symmetric admissibility; every distractor violates one rule'}


def render(family,data,language):
    ja=language=='ja'
    if family=='policy':
        rules=[]
        for r in data['rules']:
            if ja:text=f"規則 {r['id']}（優先度 {r['priority']}）: 条件 {expr_text(r['when'],language)} のとき「{ACTIONS[language][r['action']]}」。ただし {expr_text(r['except'],language)} のとき、この規則は適用しない。"
            else:text=f"Rule {r['id']} (priority {r['priority']}): if {expr_text(r['when'],language)}, action: {ACTIONS[language][r['action']]}. EXCEPTION: this rule does not apply if {expr_text(r['except'],language)}."
            rules.append(text)
        state={'task':('架空のサービスの公開規則。条件を満たし、適用除外に該当しない規則のうち、優先度の数値が最大の規則を1つだけ適用する。該当がなければ既定の操作。外部の慣習を追加せず、記載された規則だけで判断する。' if ja else 'Fictional release policy. Among rules whose condition holds and exception does NOT hold, apply ONLY the rule with the largest numeric priority. Use the default if none applies. Use only the written policy, not outside conventions.'),
               'field_definitions':FIELD_NOTES[language],'facts':data['facts'],'rules':rules,'default_action':ACTIONS[language][data['default']]}
        return state,('実行すべき操作はどれですか。' if ja else 'Which action must be executed?'),{i:ACTIONS[language][i] for i in range(4)}
    if family=='temporal':
        events=[]
        for e in data['events']:
            clock=f"{e['minute']//60:02}:{e['minute']%60:02}"
            if e['kind']=='swap':
                a,b=e['items'];text=f"容器 {a} と容器 {b} の場所を交換する。" if ja else f"Swap the locations of container {a} and container {b}."
            else:text=f"容器 {e['item']} を {e['location']} へ移す。" if ja else f"Move container {e['item']} to {e['location']}."
            events.append(f"{e['id']} / {clock} / {text}")
        state={'task':('同じ日の容器の移動記録。取消済みのIDは最初から実行されなかったものとして除外し、残りを時刻の昇順で適用する。表示順は時刻順とは限らない。交換は、その時点の2つの容器の場所を入れ替える。各場所には複数の容器を置ける。' if ja else 'Container movements within one day. Remove cancelled event IDs as if they never occurred; apply remaining events in ascending timestamp order, not display order. A swap exchanges the two containers\' current locations. A location can hold multiple containers.'),
               'initial_locations':data['initial'],'events':events,'cancelled_event_ids':data['cancelled']}
        return state,(f"最後に容器 {data['target']} はどこにありますか。" if ja else f"Where is container {data['target']} after all valid events?"),{p:p for p in data['locations']}
    state={'task':('架空の作業割当。各作業は時間枠1つを使う。すべての作業に許可された担当者と時間枠を割り当てる。同じ担当者は同じ時間枠に2つの作業を担当できない。前後関係 A→B は、Aの時間枠番号がBより厳密に小さいことを要求する。記載された全条件を満たす案は1つだけ。' if ja else 'Fictional work assignment. Every job occupies one whole slot. Assign every job an allowed worker and slot. A worker cannot do two jobs in the same slot. Each precedence A→B requires A\'s slot number to be strictly smaller than B\'s. Exactly one proposed plan meets every written constraint.'),
           'allowed_assignments':data['requirements'],'precedence':data['precedes']}
    return state,('全条件を満たす割当案はどれですか。' if ja else 'Which assignment plan satisfies every constraint?'),{i:p for i,p in enumerate(data['plans'])}


def make_fixture(family,difficulty,language,index,gold_index):
    rng=seeded(family,difficulty,language,index)
    data,gold,witness={'policy':policy,'temporal':temporal,'schedule':schedule}[family](rng,difficulty)
    state,instructions,candidates=render(family,data,language)
    order=list(candidates);rng.shuffle(order)
    where=order.index(gold);order[where],order[gold_index]=order[gold_index],order[where]
    criteria={chr(65+i):candidates[k] for i,k in enumerate(order)}
    key=chr(65+gold_index)
    if family=='schedule':witness['candidate_violations_by_label']={chr(65+i):witness['candidate_violations'][k] for i,k in enumerate(order)}
    return {'id':f'{family}-{difficulty}-{language}-{index:03}', 'family':family,'difficulty':difficulty,
            'language':language,'version':VERSION,'split':'test','independent_item':True,
            'seed_key':f'{MASTER}|{family}|{difficulty}|{language}|{index}',
            'payload':{'model':MODEL,'state':state,'questions':{'decision':{'type':'choice','instructions':instructions,'criteria':criteria}}},
            'gold_choice':key,'gold_internal':gold,'option_internal_order':order,'abstract':data,'witness':witness}


def generate():
    canonical=[]
    for family in ['policy','temporal','schedule']:
        for difficulty,n in COUNTS.items():
            for language in ['en','ja']:
                gold_positions=list(range(4))*(n//8);seeded('balance',family,difficulty,language).shuffle(gold_positions)
                for i,position in enumerate(gold_positions):canonical.append(make_fixture(family,difficulty,language,i,position))
    variants=[]
    for family in ['policy','temporal','schedule']:
        anchors=[f for f in canonical if f['family']==family and f['difficulty']=='hard' and int(f['id'].split('-')[-1])<10]
        assert len(anchors)==20
        for base in anchors:
            rev=copy.deepcopy(base);rev.update(id=base['id']+'-reverse',independent_item=False,base_id=base['id'],variant='reverse')
            q=rev['payload']['questions']['decision'];q['criteria']=dict(zip('ABCD',reversed(list(q['criteria'].values()))))
            rev['option_internal_order']=list(reversed(base['option_internal_order']))
            rev['gold_choice']=chr(65+3-(ord(base['gold_choice'])-65))
            if family=='schedule':rev['witness']['candidate_violations_by_label']={chr(65+i):rev['witness']['candidate_violations'][k] for i,k in enumerate(rev['option_internal_order'])}
            variants.append(rev)
            alt=copy.deepcopy(base);language='ja' if base['language']=='en' else 'en'
            state,inst,options=render(base['family'],base['abstract'],language)
            alt.update(id=base['id']+'-translation',independent_item=False,base_id=base['id'],variant='translation',language=language)
            alt['payload']['state']=state;alt['payload']['questions']['decision']={'type':'choice','instructions':inst,'criteria':{chr(65+i):options[k] for i,k in enumerate(base['option_internal_order'])}}
            variants.append(alt)
    seeded('request_order').shuffle(canonical);seeded('variant_order').shuffle(variants)
    return canonical+variants


def verify(items):
    checks=collections.Counter();seen=set();positions=collections.defaultdict(collections.Counter)
    for f in items:
        assert f['id'] not in seen;seen.add(f['id'])
        data=f['abstract'];family=f['family'];gold=f['gold_internal']
        if family=='policy':assert oracle.policy_answer(data)==gold
        elif family=='temporal':assert oracle.temporal_answer(data)[0]==gold
        else:assert [i for i,p in enumerate(data['plans']) if not oracle.schedule_violations(data,p)]==[gold]
        q=f['payload']['questions']['decision'];assert set(q['criteria'])==set('ABCD')
        assert len({digest(x) for x in q['criteria'].values()})==4
        assert f['option_internal_order'][ord(f['gold_choice'])-65]==gold
        if family=='schedule':
            assert [key for key,value in f['witness']['candidate_violations_by_label'].items() if not value]==[f['gold_choice']]
        assert not any(k in f['payload'] for k in ['gold_choice','witness','abstract'])
        checks['independent_oracle_agreement']+=1;checks['unique_choices']+=1
        if f['independent_item']:positions[(family,f['difficulty'],f['language'])][f['gold_choice']]+=1
    assert len([f for f in items if f['independent_item']])==552
    assert len(items)==672
    for key,counts in positions.items():assert len(set(counts.values()))==1 and set(counts)==set('ABCD'),(key,counts)
    return {'all_passed':True,'checks':dict(checks),'canonical':552,'variants':120,
            'position_counts':{'/'.join(k):dict(v) for k,v in positions.items()}}


def main(args):
    out=ROOT/'dataset'/VERSION
    out.mkdir(parents=True,exist_ok=False)
    items=generate();report=verify(items)
    text=''.join(json.dumps(f,ensure_ascii=False)+'\n' for f in items)
    (out/'items.jsonl').write_text(text)
    (out/'public-inputs.jsonl').write_text(''.join(json.dumps({'id':f['id'],'payload':f['payload']},ensure_ascii=False)+'\n' for f in items))
    report.update(version=VERSION,master_seed=MASTER,sha256=hashlib.sha256(text.encode()).hexdigest())
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    examples=[next(f for f in items if f['family']==family and f['difficulty']==difficulty and f['language']==language and f['independent_item']) for family in ['policy','temporal','schedule'] for difficulty in COUNTS for language in ['en','ja']]
    (out/'review-examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main(argparse.ArgumentParser().parse_args())
