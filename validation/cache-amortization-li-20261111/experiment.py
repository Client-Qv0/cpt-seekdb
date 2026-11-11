"""Unwarmed query prefixes and durable UPDATE interleaving, separate from frozen bench."""
import argparse, hashlib, importlib.util, json, os, re, statistics, subprocess
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
ROOT=P.parents[1]
SRC=ROOT/'validation/perf-20261110-stdio/scripts/bench.py'
SHA='2bf78d1307197b23f08e02f842594e0d8c271b706cd9ac8c303673db0b5bf5ed'
IMAGES={
 'B':('mvdb-li-review:9cea05e','14957ef07f665050d3b6bfebf180c4822acea378d5e038e41ad8d9562417407a','1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9'),
 'C2':('mvdb-li-exact:c2-3490b49','f8ccc8d89f578f5e4905827a08690161a942d041ceea06d05044528c98495bf7','b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67')}
NS=[1,5,10,20,100]
SEEDS=[3179,3181,3187]*2
spec=importlib.util.spec_from_file_location('frozen_bench',SRC)
bench=importlib.util.module_from_spec(spec)
assert bench.__name__!='__main__' and hashlib.sha256(SRC.read_bytes()).hexdigest()==SHA
if not __debug__: raise RuntimeError('Assertions must remain enabled')
spec.loader.exec_module(bench)
bench.ROOT=P/'fixtures'
bench.ENV=dict(os.environ,DOCKER_HOST='unix:///var/run/docker.sock')
def bindings():
 out={}
 for k,(tag,digest,want) in IMAGES.items():
  image='sha256:'+digest
  d=json.loads(bench.docker('image','inspect',tag).stdout)[0];assert d['Id']==image
  actual=bench.docker('run','--rm','--network=none','--entrypoint','sha256sum',image,'/app/minivectordb').stdout.decode().split()[0]
  assert actual==want,(k,actual)
  out[k]={'image':image,'tag':tag,'binary_sha256':actual}
 return out
def changed_truth(w):
 # Parse actual fixture INSERT tuples, rather than reproduce its RNG.
 tuples=[m for sql in w['batches'] for m in re.finditer(r"\((\d+),'g([0-4])','(\[[^']+\])'\)",sql)]
 assert len(tuples)==10000 and [int(x[1]) for x in tuples]==list(range(10000))
 ids=np.arange(len(tuples))
 a=np.array([json.loads(x[3]) for x in tuples],dtype=np.float32).astype(np.float64)
 groups=np.array([int(x[2]) for x in tuples]);assert np.array_equal(groups,ids%5)
 groups[0]=5
 out=[]
 for sql,t in zip(w['queries'],w['truth']):
  if t['group']!=0:
   out.append(t);continue
  q=np.array(json.loads(re.search(r"'(\[[^']+\])'",sql)[1]),dtype=np.float32).astype(np.float64)
  eligible=ids[groups==0];dist=np.sqrt(np.sum((a[eligible]-q)**2,axis=1,dtype=np.float64))
  j=np.lexsort((eligible,dist))[:10]
  out.append({'group':0,'rows':[[int(eligible[i]),float(dist[i])] for i in j]})
 return out
def run(out,data,image,w,modified,k):
 assert not data.exists()
 s=bench.Session(image,out,data);qt=[];ut=[];load=[];checks=[];changed=False
 try:
  assert s.info['Image']==image
  assert s.snapshots[0]['files']['cpuset.cpus.effective'].strip()=='0-1'
  s.request(w['create'])
  for sql in w['batches']:
   r,t=s.request(sql);assert r['affected_rows']==100;load.append(t)
  s.capture('after_load')
  for i,sql in enumerate(w['queries']):
   if k and i and i%k==0:
    changed=not changed
    r,t=s.request("UPDATE bench SET grp='%s' WHERE id=0;"%('g5' if changed else 'g0'))
    assert r['affected_rows']==1;ut.append(t)
   r,t=s.request(sql);qt.append(t);checks.append((r,(modified if changed else w['truth'])[i]))
  s.capture('after_measured_requests')
  r,_=s.request('SELECT grp FROM bench WHERE id=0;')
  assert r['rows']==[['g5' if changed else 'g0']]
  s.close()
 except BaseException:
  if not (out/'container.json').exists():s.abort()
  raise
 errors=[bench.check(a,b) for a,b in checks]
 assert not s.info_after['State']['OOMKilled'] and s.info_after['State']['ExitCode']==0
 assert len(qt)==100 and len(ut)==(99//k if k else 0)
 for x in s.snapshots:
  f=x['files'];e=dict(row.split() for row in f['memory.events'].splitlines())
  assert int(e['oom'])==int(e['oom_kill'])==0
 return {'image':image,'startup_s':s.startup,'load_s':sum(load),'query_s':sum(qt),'update_s':sum(ut),'total_s':sum(qt)+sum(ut),'prefix_s':{str(n):sum(qt[:n]) for n in NS},'query_times':qt,'update_times':ut,'oracle_checks':len(errors),'max_distance_error':max(errors),'memory_peak':max(int(x['files']['memory.peak']) for x in s.snapshots)}
def summarize(rows,keys):
 result={}
 for metric,get in keys.items():
  vals={}
  for kind in ['aa','bc']:
   pairs=[row for row in rows if row['kind']==kind];assert len(pairs)==6
   vals[kind]=[100*(1-get(row['right'])/get(row['left'])) for row in pairs]
  noise=max(map(abs,vals['aa']));d=vals['bc'];med=statistics.median(d);wins=sum(x>0 for x in d)
  result[metric]={'aa_pct':vals['aa'],'noise_max_abs_pct':noise,'paired_reduction_pct':d,'median_pct':med,'wins':wins,'stable_win':wins>=5 and med>noise}
 return result
def main():
 parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['cold','write']);a=parser.parse_args()
 out=P/('runs-'+a.phase);out.mkdir()
 data=Path('/home/li')/('mvdb-amortization-'+a.phase+'-20261111');data.mkdir()
 (bench.ROOT/'results').mkdir(parents=True,exist_ok=True)
 ident=bindings();bench.dump(out/'bindings.json',ident)
 for k in ([0] if a.phase=='cold' else [5,20]):
  rows=[]; dest=out/str(k);dest.mkdir()
  for kind in ['aa','bc']:
   for i,seed in enumerate(SEEDS):
    w=bench.prepare(seed,10000,128,100);modified=changed_truth(w) if k else None
    pair={'kind':kind,'round':i+1,'seed':seed,'fixture_sha256':bench.sha(bench.ROOT/'results'/f'workload-{seed}-10000-128-100'/'workload.json.gz')}
    sides=['left','right'] if i%2==0 else ['right','left']
    pair['order']=sides
    for side in sides:
     tag='C2' if kind=='bc' and side=='right' else 'B'
     name=f'{k}-{kind}-{i+1}-{side}'
     print('start',name,flush=True)
     r=run(dest/name,data/name,ident[tag]['image'],w,modified,k)
     pair[side]=r;bench.dump(dest/name/'result.json',r)
    rows.append(pair);bench.dump(dest/f'{kind}-{i+1}.json',pair)
  keys={str(n):lambda r,n=n:r['prefix_s'][str(n)] for n in NS} if not k else {n:lambda r,n=n:r[n] for n in ['query_s','update_s','total_s']}
  summary=summarize(rows,keys)
  if not k:
   candidates=[n for n in NS if all(summary[str(x)]['stable_win'] for x in NS if x>=n)]
   summary['earliest_stable_observed']=min(candidates) if candidates else None
  bench.dump(dest/'summary.json',summary)
 (out/'PASS').write_text('all paired comparisons and oracle checks completed\n')
if __name__=='__main__':main()
