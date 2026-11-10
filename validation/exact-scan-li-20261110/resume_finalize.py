from pathlib import Path
import json
p=Path(__file__).parent
for name in ['million-baseline','million-c2','million-vector-baseline','million-vector-c2']:
 d=json.loads((p/name).read_text()); anon=[]; peak=[]; oom=[]; passed=[]
 def walk(x):
  if isinstance(x,dict):
   for k,v in x.items():
    if k in ['anon','anon_bytes'] and isinstance(v,(int,float)):anon.append(v)
    if k in ['peak','memory_peak_bytes'] and isinstance(v,(int,float)):peak.append(v)
    if k=='memory.peak' and isinstance(v,str):peak.append(int(v))
    if k=='memory.stat' and isinstance(v,str):anon.append(int(dict(line.split() for line in v.splitlines()).get('anon',0)))
    if k in ['events','memory.events'] and isinstance(v,str):
     q=dict(line.split() for line in v.splitlines());oom.append(int(q.get('oom_kill',0)))
    if k=='passed' and isinstance(v,bool):passed.append(v)
    walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(d)
 print(name,'keys',list(d),'anonMax',max(anon,default=0),'peakMax',max(peak,default=0),'oomKillMax',max(oom,default=0),'passed',passed)
 if 'cases' in d:print('casekeys',list(d['cases'][0]) if d['cases'] else [])
