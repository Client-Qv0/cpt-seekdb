from pathlib import Path
import json,hashlib,subprocess,platform,datetime,os
p=Path(__file__).parent;repo=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
g=json.loads((p/'FINAL_GATES.json').read_text());assert g['passed'] and all(g['checks'].values())
subprocess.run(['git','-c','safe.directory='+str(repo),'-C',str(repo),'diff','--exit-code','3490b490cfeb2b0ece00bb637f231e1b2f05ca80','--','src','CMakeLists.txt','Dockerfile','.dockerignore','tests'],check=True)
env={'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'client_date':'2026-11-11','platform':platform.platform(),'affinity':sorted(os.sched_getaffinity(0)),'python':platform.python_version()}
for k,c in [('compiler',['g++','--version']),('cmake',['cmake','--version']),('filesystem',['findmnt','-T',str(repo),'-o','SOURCE,FSTYPE,MAJ:MIN'])]:env[k]=subprocess.check_output(c,text=True)
(p/'FINAL_ENVIRONMENT.json').write_text(json.dumps(env,indent=2)+'\n')
inputs=json.loads((p/'candidate-production-manifest.json').read_text())['files']
for e in inputs:assert sha(repo/e['path'])==e['sha256'],e['path']
bins=[]
for f in [repo/'build-exact-c1/minivectordb',repo/'build-exact-c2/minivectordb',Path('/home/li/minivectordb-review-20261110/build-server-review/minivectordb')]:
 if f.exists():bins.append({'path':str(f),'sha256':sha(f),'bytes':f.stat().st_size})
binding={'functional_commit':'3490b490cfeb2b0ece00bb637f231e1b2f05ca80','production_inputs':inputs,'binaries':bins,'agent_bytes':(repo/'agent/conversation.json').stat().st_size,'agent_sha256':sha(repo/'agent/conversation.json'),'handoff_sha256':sha(repo/'TEAM_HANDOFF.md')}
assert binding['agent_bytes']<131072 and binding['agent_sha256']==g['agent_sha256']
(p/'FINAL_BINDING.json').write_text(json.dumps(binding,indent=2)+'\n')
raw=[];pub=[]
for f in sorted(p.rglob('*')):
 if not f.is_file() or '__pycache__' in f.parts or f.name=='EVIDENCE_MANIFEST.json':continue
 rel=f.relative_to(p); item={'path':str(rel),'bytes':f.stat().st_size,'sha256':sha(f)}
 with f.open('rb') as s:elf=s.read(4)==b'\x7fELF'
 retain=rel.parts[0]=='source-7637' or f.suffix in ['.gz','.tar','.data','.jsonl','.o','.a','.so'] or elf or f.stat().st_size>2097152
 (raw if retain else pub).append(item)
ig=p/'.gitignore';before=ig.read_text().split('# Final retained local artifacts')[0] if ig.exists() else ''
ig.write_text(before.rstrip()+'\n\n# Final retained local artifacts\n**/__pycache__/\n'+'\n'.join('/'+e['path'] for e in raw)+'\n')
for e in pub:
 if e['path']=='.gitignore':e.update(bytes=ig.stat().st_size,sha256=sha(ig))
(p/'EVIDENCE_MANIFEST.json').write_text(json.dumps({'published':pub,'retained_local_only':raw,'manifest_excludes_itself':True,'official_assessment_submitted':False,'source_binding':'FINAL_BINDING.json'},indent=2)+'\n')
print('Final manifest:',len(pub),'published,',len(raw),'retained local; bytes',sum(e['bytes'] for e in pub),'material',binding['agent_bytes'])
