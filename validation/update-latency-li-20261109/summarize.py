from pathlib import Path
import json,gzip,hashlib,statistics,re
p=Path(__file__).parent; hist=p.parent/'cardinality-20261109'; s=json.loads((p/'paired-original/summary.json').read_text()); out={'all_planned_runs_passed':s['all_planned_runs_passed'],'identities_unchanged':s.get('identities_unchanged'),'workloads':{},'diagnostics':{},'sql_history_matches':{}}
for name,w in s['workloads'].items():
 out['workloads'][name]={'variants':{},'paired_B_over_V2':w['paired_ratios'],'negative_median_timing_benefit':w['negative_median_timing_benefit']}
 for v,data in w['variants'].items():out['workloads'][name]['variants'][v]={'runs':data['runs'],'runs_passed':data['runs_passed'],'timings':data['timings'],'resources':data['resources']}
for f in (p/'paired-original').glob('*.sql.gz'):
 a=gzip.open(f,'rb').read(); b=gzip.open(hist/'paired-candidate-v2'/f.name,'rb').read();out['sql_history_matches'][f.name]={'identical':a==b,'uncompressed_sha256':hashlib.sha256(a).hexdigest()};assert a==b
for f in sorted(p.glob('diagnostic-*/run.json')):
 d=json.loads(f.read_text()); item={'passed':d.get('passed'),'binary_sha256':d['binary_sha256'],'original_sql_sha256':d['original_sql_sha256'],'diagnostic_strace':d['diagnostic_strace'],'commands':[{'sql':e['command']['sql'],'timing':e['timing']} for e in d['commands'] if e['timing']], 'instrumented_timings':[json.loads(m) for m in re.findall(r'DIAGNOSTIC (\{[^\n]+\})',d['container']['stderr_tail'])], 'state':d['container']['docker_final_state']}
 trace=f.parent/'update.strace'
 if trace.exists():
  lines=trace.read_text().splitlines(); item['trace_lines']=lines; item['sync_seconds']=[float(x) for line in lines if 'fdatasync(' in line for x in re.findall(r'<([0-9.]+)>$',line)]
 out['diagnostics'][f.parent.name]=item
(p/'RESULTS.json').write_text(json.dumps(out,indent=2)+'\n')
for n,w in out['workloads'].items():
 print(n)
 for k in ['write_batches_seconds','warm_queries_seconds','update_cache_invalidation_seconds','restart_startup_to_first_response_seconds']:
  if k not in w['paired_B_over_V2']:continue
  print(k, 'B',w['variants']['baseline']['timings'][k]['values'],'V2',w['variants']['candidate']['timings'][k]['values'],'B/V2 median',w['paired_B_over_V2'][k]['median'])
 print('anon B/V2',*[w['variants'][v]['resources']['main']['sampled_and_kernel_maxima']['anon_bytes']['median'] for v in ['baseline','candidate']]); print('negative',w['negative_median_timing_benefit'])
for n,d in out['diagnostics'].items():print(n,{k:v for k,v in d.items() if k in ['passed','commands','instrumented_timings','sync_seconds']})
