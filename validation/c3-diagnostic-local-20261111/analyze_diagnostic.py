import pathlib,json,statistics,hashlib,gzip
R=pathlib.Path(__file__).resolve().parent
D=R/'diagnostic-runs/results'
records=[]
for folder in sorted(D.glob('c3stage-*')):
 b=json.loads((folder/'baseline/result.json').read_text())
 d=json.loads((folder/'instrumented/result.json').read_text())
 assert b['workload_sha256']==d['workload_sha256']
 stages={}
 for line in (folder/'instrumented/initial/stderr.log').read_text().splitlines():
  assert line.startswith('C3DIAG '),line
  value=json.loads(line[7:]);seq=value['sequence'];assert seq not in stages;stages[seq]=value
 n=d['queries'];start=1+d['rows']//d['write_batch']+1+min(10,n)+1
 hot=[stages[start+i] for i in range(n)]
 assert all(x['hot'] for x in hot)
 assert len(d['query_times'])==n
 def fractions(indices):
  e2e=sum(d['query_times'][i] for i in indices)
  ns={k:sum(hot[i][k] for i in indices) for k in ['winner_ns','get_ns','unpack_ns','project_ns','construct_ns']}
  return {'queries':len(indices),'end_to_end_s':e2e,**ns,'winner_fraction':ns['winner_ns']/1e9/e2e}
 groups={'all':fractions(list(range(n))),'filtered':fractions(list(range(1,n,2))),'unfiltered':fractions(list(range(0,n,2)))}
 resources={}
 for label in ['baseline','instrumented']:
  phases=[]
  for phase in ['initial','restart']:
   snapshots=json.loads((folder/label/phase/'resources.json').read_text())
   for s in snapshots:
    fields=s['files'];events=dict(x.split() for x in fields['memory.events'].splitlines())
    assert int(events.get('oom',0))==0 and int(events.get('oom_kill',0))==0
    phases.append({'phase':phase,'label':s['label'],'memory_peak':int(fields['memory.peak']),'events':events})
  resources[label]=phases
 records.append({'round':folder.name,'seed':d['seed'],'groups':groups,'baseline_times':b['times'],'instrumented_times':d['times'],'instrumentation_relative_e2e_change':d['times']['query_s']/b['times']['query_s']-1,'resources':resources,'oracle_checks':b['oracle_checks']+d['oracle_checks'],'recall':min(b['recall'],d['recall']),'max_distance_error':max(b['maximum_distance_error'],d['maximum_distance_error'])})
assert len(records)==6
median=statistics.median(x['groups']['all']['winner_fraction'] for x in records)
result={'baseline_commit':'87c2778ed0688e6e56152baf02bc4f4355667458','scope':'local WSL reproduction, instrumented diagnosis, not production performance candidate or official scorer','six_rounds':records,'median_winner_fraction':median,'median_filtered_fraction':statistics.median(x['groups']['filtered']['winner_fraction'] for x in records),'median_unfiltered_fraction':statistics.median(x['groups']['unfiltered']['winner_fraction'] for x in records),'gate_threshold':0.05,'below_gate':median<0.05,'substage_nested_timers_summed_into_total':False,'timer_overhead':'winner total includes substage chrono and counter costs; no subtraction of estimated costs; JSONL serialization/flush included in e2e denominator only','median_instrumentation_relative_e2e_change':statistics.median(x['instrumentation_relative_e2e_change'] for x in records),'correctness':'Frozen exhaustive NumPy reference, actual returned ordered IDs, filters, duplicates, FP32 distances and Recall checked outside timer and cgroup','official_score_prediction':None,'physical_IO_estimate':None}
(R/'diagnostic-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'median_winner_percent':100*median,'filtered_percent':100*result['median_filtered_fraction'],'unfiltered_percent':100*result['median_unfiltered_fraction'],'below_gate':result['below_gate'],'instrumentation_change_percent':100*result['median_instrumentation_relative_e2e_change'],'oracle_checks':sum(x['oracle_checks'] for x in records),'rounds':[{'round':x['round'],'winner_percent':100*x['groups']['all']['winner_fraction'],'baseline_query_s':x['baseline_times']['query_s'],'diagnostic_query_s':x['instrumented_times']['query_s']} for x in records]}),flush=True)
