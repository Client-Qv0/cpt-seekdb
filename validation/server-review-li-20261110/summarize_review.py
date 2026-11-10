from pathlib import Path
import json,statistics,hashlib,re,subprocess
p=Path(__file__).parent; repo=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dist(v):
 return {'values':v,'median':statistics.median(v),'min':min(v),'max':max(v),'cv':statistics.pstdev(v)/statistics.mean(v) if min(v)>=0 and statistics.mean(v)>0 else None}
out={'source_commit':'9cea05e182875ae16f3f3c9c8e9cc688a65d653c','baseline_commit':'6576b24e0774eb11352ab5bca3372cda32f8efd9','native_binary_sha256':sha(repo/'build-server-review/minivectordb'),'dockerfile_sha256':sha(repo/'Dockerfile'),'agent_sha256':sha(repo/'agent/conversation.json'),'agent_bytes':(repo/'agent/conversation.json').stat().st_size,'workloads':{}}
for mode,expected in [('paired-main',6),('paired-overflow',3)]:
 rounds=sorted((p/mode/'results').glob('li-review-*')); assert len(rounds)==expected,(mode,len(rounds)); pairs=[]
 for folder in rounds:
  pair={label:json.loads((folder/label/'result.json').read_text()) for label in ['base','candidate']}
  assert all(r['recall']==1 and r['id_order_types_filter_duplicates_checked'] for r in pair.values())
  assert pair['base']['workload_sha256']==pair['candidate']['workload_sha256']
  entry={'round':folder.name,'records':pair,'main_resources':{}}
  for label in pair:
   samples=json.loads((folder/label/'initial/resources.json').read_text()); peaks=[int(s['files']['memory.peak']) for s in samples]; events=[dict(line.split() for line in s['files']['memory.events'].splitlines()) for s in samples]; counters={key:max(int(e.get(key,0)) for e in events) for key in ['max','oom','oom_kill']}; entry['main_resources'][label]={'memory_peak':max(peaks),'events':counters}
  entry['container_states']={label:{phase:json.loads((folder/label/phase/'container.json').read_text())['after']['State'] for phase in ['initial','restart']} for label in pair}
  assert all(not state['OOMKilled'] and state['ExitCode']==0 for phases in entry['container_states'].values() for state in phases.values())
  pairs.append(entry)
 metrics={}
 for metric in pairs[0]['records']['base']['times']:
  b=[e['records']['base']['times'][metric] for e in pairs];c=[e['records']['candidate']['times'][metric] for e in pairs];changes=[1-y/x for x,y in zip(b,c)];metrics[metric]={'base':dist(b),'candidate':dist(c),'paired_time_reduction':dist(changes),'candidate_faster_rounds':sum(y<x for x,y in zip(b,c))}
 out['workloads'][mode]={'pairs':pairs,'metrics':metrics,'memory_peak':{v:dist([e['main_resources'][v]['memory_peak'] for e in pairs]) for v in ['base','candidate']}}
for label in ['official-native-all','official-all','official-crud','official-handshake']:
 d=json.loads((p/label/'result.json').read_text()); out[label]={'passed':d['passed'],'cases':len(d.get('cases',[]))};assert d['passed']
out['container_recovery']=json.loads((p/'container-recovery/result.json').read_text())
assert (p/'pipeline.exit').read_text().strip()=='0'
(p/'REVIEW_RESULTS.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
for name,w in out['workloads'].items():
 print(name)
 for k in ['write_s','query_s','restart_ready_s']:
  v=w['metrics'][k];print(k,'B',v['base']['values'],'C',v['candidate']['values'],'median reduction',v['paired_time_reduction']['median'],'faster',v['candidate_faster_rounds'])
 print('memory',[w['memory_peak'][v]['median'] for v in ['base','candidate']])
print('public',out['official-all'],'recovery',out['container_recovery'].get('status'))
