from pathlib import Path
import json, statistics, hashlib
p=Path(__file__).parent
out={}
for name,n in [('c1-b-main',6),('c1-b-overflow',3),('c2-c1-main',6),('c2-c1-overflow',3),('final-b-main',6),('final-b-overflow',3),('final-b-holdout',3)]:
 d=p/name
 m=json.loads((d/'adapter-manifest.json').read_text())
 assert m['exit_code']==0
 labels=list(m['images']); assert len(labels)==2
 dirs=sorted(x for x in (d/'results').iterdir() if (x/labels[0]/'result.json').exists())
 assert len(dirs)==n,(name,len(dirs))
 rows=[]
 for rd in dirs:
  results=[json.loads((rd/l/'result.json').read_text()) for l in labels]
  assert results[0]['workload_sha256']==results[1]['workload_sha256']
  assert all(x['recall']==1 and x['id_order_types_filter_duplicates_checked'] and x['limits']=={'memory':134217728,'swap':0,'cpus':2,'cpuset':'0,1'} for x in results)
  resources={}
  for l in labels:
   resources[l]={}
   for phase in ('initial','restart'):
    snapshots=json.loads((rd/l/phase/'resources.json').read_text())
    events=[{k:int(v) for k,v in (line.split() for line in x['files']['memory.events'].splitlines())} for x in snapshots]
    assert all(e.get('oom',0)==0 and e.get('oom_kill',0)==0 for e in events)
    state=json.loads((rd/l/phase/'container.json').read_text())['after']['State']
    assert not state['OOMKilled'] and state['ExitCode']==0
    resources[l][phase]={'peak_bytes':max(int(x['files']['memory.peak']) for x in snapshots),'events':events[-1]}
  rows.append({'round':rd.name,'seed':results[0]['seed'],'workload_sha256':results[0]['workload_sha256'],'times':{l:r['times'] for l,r in zip(labels,results)},'resources':resources,'oracle_checks':{l:r['oracle_checks'] for l,r in zip(labels,results)}})
 metrics={}
 for metric in rows[0]['times'][labels[0]]:
  values=[100*(1-r['times'][labels[1]][metric]/r['times'][labels[0]][metric]) for r in rows]
  metrics[metric]={'paired_reduction_percent':values,'median_reduction_percent':statistics.median(values),'wins':sum(v>0 for v in values)}
 out[name]={'images':m['images'],'pairs':rows,'metrics':metrics}
dest=p/'COMPARISONS.json'; assert not dest.exists()
dest.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
for name,data in out.items():
 print(name, {k:(round(v['median_reduction_percent'],3),v['wins']) for k,v in data['metrics'].items() if k in ('query_s','filtered_query_s','unfiltered_query_s','write_s','restart_ready_s')})
