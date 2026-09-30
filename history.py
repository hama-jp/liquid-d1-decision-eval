"""Recover immutable transport history rather than trusting post-scoring files."""
import json


def read_attempts(root):
    result=[]
    for folder in (root/'runs').glob('*'):
        # Transport journal is authoritative if present. Otherwise old v1 runs
        # have complete responses in requests.jsonl.
        path=folder/'transport.jsonl'
        if not path.exists():path=folder/'requests.jsonl'
        if not path.exists():continue
        for line in path.read_text().splitlines():
            if not line.strip():continue
            r=json.loads(line);r['_run']=folder.name;result.append(r)
    return sorted(result,key=lambda r:(r.get('at',''),r.get('completed_monotonic',0)))


def terminal(record):
    status=record.get('http_status',0)
    return status==200 or (isinstance(status,int) and 400<=status<500 and status!=429)
