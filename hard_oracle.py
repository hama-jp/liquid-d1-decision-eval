"""Independent, deterministic checkers used only on hidden fixture metadata."""
import sqlite3


def expr_sql(expression):
    if expression['kind']=='atom':
        op={'ge':'>=','lt':'<','eq':'='}[expression['op']]
        return f"({expression['field']} {op} {int(expression['value'])})"
    op=' AND ' if expression['kind']=='all' else ' OR '
    return '('+op.join(expr_sql(child) for child in expression['children'])+')'


def policy_answer(data):
    db=sqlite3.connect(':memory:')
    columns=list(data['facts'])
    db.execute('CREATE TABLE facts ('+','.join(k+' INTEGER' for k in columns)+')')
    db.execute('INSERT INTO facts VALUES ('+','.join('?' for _ in columns)+')',list(data['facts'].values()))
    applies=[]
    for rule in data['rules']:
        sql='SELECT ('+expr_sql(rule['when'])+') AND NOT ('+expr_sql(rule['except'])+') FROM facts'
        if db.execute(sql).fetchone()[0]:applies.append(rule)
    db.close()
    winner=max(applies,key=lambda r:r['priority']) if applies else None
    return winner['action'] if winner else data['default']


def temporal_answer(data):
    # Follow only the queried container backwards. This is independent of the
    # generator's forward map updates and gives a short proof witness.
    item=data['target'];trace=[]
    for event in sorted(data['events'],key=lambda e:e['minute'],reverse=True):
        if event['id'] in data['cancelled']:continue
        if event['kind']=='move' and event['item']==item:
            trace.append(event['id'])
            return event['location'],trace
        if event['kind']=='swap':
            a,b=event['items']
            if item==a:item=b;trace.append(event['id'])
            elif item==b:item=a;trace.append(event['id'])
    return data['initial'][item],trace


def schedule_violations(data,plan):
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE assignments(job TEXT PRIMARY KEY,worker TEXT,slot INTEGER); CREATE TABLE allowed_workers(job TEXT,worker TEXT); CREATE TABLE allowed_slots(job TEXT,slot INTEGER); CREATE TABLE precedes(a TEXT,b TEXT);')
    db.executemany('INSERT INTO assignments VALUES(?,?,?)',[(j,v['worker'],v['slot']) for j,v in plan.items()])
    db.executemany('INSERT INTO allowed_workers VALUES(?,?)',[(j,w) for j,r in data['requirements'].items() for w in r['workers']])
    db.executemany('INSERT INTO allowed_slots VALUES(?,?)',[(j,t) for j,r in data['requirements'].items() for t in r['slots']])
    db.executemany('INSERT INTO precedes VALUES(?,?)',data['precedes'])
    violations=[]
    for row in db.execute('SELECT a.job FROM assignments a WHERE NOT EXISTS (SELECT 1 FROM allowed_workers w WHERE a.job=w.job AND a.worker=w.worker)'):
        violations.append(('worker',row[0]))
    for row in db.execute('SELECT a.job FROM assignments a WHERE NOT EXISTS (SELECT 1 FROM allowed_slots s WHERE a.job=s.job AND a.slot=s.slot)'):
        violations.append(('slot',row[0]))
    for a,b in db.execute('SELECT a.job,b.job FROM assignments a JOIN assignments b ON a.job<b.job AND a.worker=b.worker AND a.slot=b.slot'):
        violations.append(('collision',a,b))
    for a,b in db.execute('SELECT p.a,p.b FROM precedes p JOIN assignments a ON a.job=p.a JOIN assignments b ON b.job=p.b WHERE a.slot>=b.slot'):
        violations.append(('precedence',a,b))
    db.close()
    return sorted(violations)
