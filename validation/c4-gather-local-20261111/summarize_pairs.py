import pathlib,json,statistics,hashlib
R=pathlib.Path(__file__).resolve().parent
def counters(text):return {line.split()[0]:int(line.split()[1]) for line in text.splitlines() if len(line.split())==2}
records=[];tables=[]
for phase in ['aa1','main','holdout','overflow']:
 for file in sorted((R/phase/'results').glob('*/*/result.json')):
  result=json.loads(file.read_text());label=file.parent.name;pair=file.parent.parent.name
  assert result['recall']==1 and result['id_order_types_filter_duplicates_checked']
  phases=[]
  for stage in ['initial','restart']:
   raw=json.loads((file.parent/stage/'resources.json').read_text())
   peaks=[];anon=[];cached=[];events=[];pressure=[];scan=[]
   for item in raw:
    f=item['files'];peaks.append(int(f['memory.peak']));s=counters(f['memory.stat']);e=counters(f['memory.events'])
    assert int(f['memory.max'])==134217728 and int(f['memory.swap.max'])==0
    assert e['oom']==0 and e['oom_kill']==0
    anon.append(s['anon']);cached.append(s['file']);events.append(e);pressure.append(f['memory.pressure']);scan.append(s['pgscan'])
   phases.append({'stage':stage,'cgroup_memory_peak_bytes':max(peaks),'max_sampled_anon_bytes':max(anon),'max_sampled_file_bytes':max(cached),'memory_events':events[-1],'last_memory_pressure':pressure[-1],'max_sampled_pgscan':max(scan),'io_stat_at_ready':raw[0]['files']['io.stat'],'io_stat_before_shutdown':raw[-1]['files']['io.stat'],'raw_file':str((file.parent/stage/'resources.json').relative_to(R)).replace('\\','/')})
  records.append({'phase':phase,'pair':pair,'label':label,'times':result['times'],'checks':result['oracle_checks'],'max_distance_error':result['maximum_distance_error'],'limits':result['limits'],'resources':phases,'io_window':result['io_window']})
 for label in ['A','B']:
  rr=[r for r in records if r['phase']==phase and r['label']==label]
  if not rr:continue
  stages=[x for r in rr for x in r['resources']]
  tables.append({'phase':phase,'label':label,'runs':len(rr),'peak_min_bytes':min(x['cgroup_memory_peak_bytes'] for x in stages),'peak_max_bytes':max(x['cgroup_memory_peak_bytes'] for x in stages),'anon_max_sample_bytes':max(x['max_sampled_anon_bytes'] for x in stages),'file_max_sample_bytes':max(x['max_sampled_file_bytes'] for x in stages),'pgscan_max':max(x['max_sampled_pgscan'] for x in stages),'oom':0,'median_times':{k:statistics.median(r['times'][k] for r in rr) for k in rr[0]['times']}})
summary={'records':records,'summary':tables,'oracle_checks':sum(x['checks'] for x in records),'cgroup_memory_limit_bytes':134217728,'cpu_quota':2,'cpu_set':'0,1','memory_notes':['memory.peak is cgroup peak, not RSS.','Anonymous and file maxima are observed phase snapshots and need not occur at the instant of memory.peak.','No working-set boundary or absence of all memory leaks can be inferred from these bounded vector workloads.'],'io_notes':['Raw io.stat and process IO remain in resource files.','Shared WSL block device and writeback attribution limit inference; counters are not file sizes and are not an official physical I/O score.'],'cached_note':'first_query is a new process/cache after independent data load; host and device caches are not globally flushed; preheated query follows 10 warmups.','formal_submission':False}
(R/'resources-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for row in tables:print(json.dumps(row))
