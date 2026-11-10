#!/usr/bin/env python3
"""Evaluate all six frozen A/A pairs, without selecting or changing rounds."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

p = argparse.ArgumentParser()
p.add_argument('batch', type=Path)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()
manifest = json.loads((a.batch / 'adapter-manifest.json').read_text())
assert manifest.get('exit_code') == 0, 'A/A batch must complete successfully first'
assert manifest['images']['a1']['id'] == manifest['images']['a2']['id']
rounds = sorted((a.batch / 'results').glob('*/a1/result.json'))
assert len(rounds) == 6, f'expected six complete pairs, found {len(rounds)}'
records = []
for first in rounds:
    second = first.parent.parent / 'a2' / 'result.json'
    left, right = [json.loads(x.read_text()) for x in (first, second)]
    assert left['workload_sha256'] == right['workload_sha256']
    assert left['recall'] == right['recall'] == 1.0
    assert left['limits'] == right['limits'] == {'memory':134217728,'swap':0,'cpus':2,'cpuset':'0,1'}
    q1, q2 = [x['times']['query_s'] for x in (left, right)]
    resources = []
    for label in ('a1', 'a2'):
        for phase in ('initial', 'restart'):
            path = first.parent.parent / label / phase / 'resources.json'
            snapshots = json.loads(path.read_text())
            events = [{k:int(v) for k,v in (line.split() for line in s['files']['memory.events'].splitlines())} for s in snapshots]
            assert all(e.get('oom',0) == e.get('oom_kill',0) == 0 for e in events), 'OOM invalidates batch'
            resources.append({'label':label,'phase':phase,'path':str(path),'peak_bytes':max(int(s['files']['memory.peak']) for s in snapshots),'events':events[-1]})
    records.append({'round':first.parent.parent.name,'seed':left['seed'],'a1_query_s':q1,'a2_query_s':q2,'signed_change_percent':100*(q2/q1-1),'absolute_change_percent':100*abs(q2/q1-1),'oracle_checks':left['oracle_checks']+right['oracle_checks'],'workload_sha256':left['workload_sha256'],'result_sha256':{str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in (first,second)},'resources':resources})
changes = [r['absolute_change_percent'] for r in records]
median, maximum = statistics.median(changes), max(changes)
result = {'batch':str(a.batch),'definition':'100 * abs(a2.query_s / a1.query_s - 1), each complete paired round; median across all six pairs','required_pairs':6,'pairs':records,'median_absolute_change_percent':median,'maximum_absolute_change_percent':maximum,'thresholds_percent':{'median_maximum':3,'pair_maximum':10},'passed':median <= 3 and maximum <= 10,'image':manifest['images']['a1'],'frozen_sha256':manifest['frozen_sha256'],'adapter_sha256':manifest['adapter_sha256'],'scope':'Current server A/A calibration only; no optimization benefit or official score claim'}
assert not a.output.exists(), 'never overwrite calibration evidence'
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:result[k] for k in ('batch','median_absolute_change_percent','maximum_absolute_change_percent','passed')},indent=2))
