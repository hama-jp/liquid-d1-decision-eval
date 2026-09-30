"""Offline verification of the published result, dataset and provenance."""
import hashlib
import json
from pathlib import Path
import hardbench
from client import digest
from history import read_attempts
ROOT=Path(__file__).resolve().parent

def main():
    expected=json.loads((ROOT/'evidence/expected-summary.json').read_text())
    actual=json.loads((ROOT/'final-summary.json').read_text())
    for key,value in expected.items():
        assert actual[key]==value, f"Final summary mismatch: {key}"
    path=ROOT/'dataset/private-decisions-v5/items.jsonl'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='ae041f64200422422f8cb1b3307c579a697ed10ca11e9b528bec4e7e1d0f6f60'
    cases=[json.loads(s) for s in path.read_text().splitlines()]
    hardbench.verify(cases)
    regenerated=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in hardbench.generate())
    assert regenerated==path.read_text(), 'Generator reproduction mismatch'
    attempts=read_attempts(ROOT)
    assert len(attempts)==853
    assert all(digest(r['request'])==r['request_sha256'] for r in attempts)
    primary=json.loads((ROOT/'hard-summary.json').read_text())['primary']
    assert [(r['family'],r['correct'],r['n']) for r in primary]==[('policy',66,120),('temporal',32,120),('schedule',68,120)]
    for name,wanted in json.loads((ROOT/'evidence/public-artifact-manifest.json').read_text())['sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==wanted, f"Artifact changed: {name}"
    print('PASS: 853 attempts, all reported summaries, 672 verified/reproduced items, public artifact hashes; no API calls.')
if __name__=='__main__':main()
