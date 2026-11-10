from pathlib import Path
import hashlib,json,platform,os,subprocess
p=Path(__file__).parent; repo=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
env={'platform':platform.platform(),'python':platform.python_version(),'affinity':sorted(os.sched_getaffinity(0))}
for key,cmd in [('compiler',['g++','--version']),('cmake',['cmake','--version']),('filesystem',['findmnt','-T',str(repo),'-o','SOURCE,FSTYPE,MAJ:MIN']),('memory',['free','-h'])]:env[key]=subprocess.check_output(cmd,text=True)
(p/'environment.json').write_text(json.dumps(env,indent=2)+'\n')
production=[]
for f in sorted((repo/'src').rglob('*')):
 if f.is_file():production.append({'path':str(f.relative_to(repo)),'sha256':sha(f),'bytes':f.stat().st_size})
for name in ['CMakeLists.txt','Dockerfile','.dockerignore','agent/conversation.json']:production.append({'path':name,'sha256':sha(repo/name),'bytes':(repo/name).stat().st_size})
(p/'source-binding.json').write_text(json.dumps({'source_commit':'9cea05e182875ae16f3f3c9c8e9cc688a65d653c','files':production,'binary_sha256':sha(repo/'build-server-review/minivectordb')},indent=2)+'\n')
published=[];retained=[]
for f in sorted(p.rglob('*')):
 if not f.is_file() or '__pycache__' in f.parts or f.name=='EVIDENCE_MANIFEST.json':continue
 rel=str(f.relative_to(p)); item={'path':rel,'bytes':f.stat().st_size,'sha256':sha(f)}
 (retained if f.suffix=='.gz' else published).append(item)
databases=[]
for dirname in ['mvdb-review-main-data-20261110','mvdb-review-overflow-data-20261110','mvdb-review-recovery-data-20261110']:
 for f in sorted((Path('/home/li')/dirname).rglob('*')):
  if f.is_file():databases.append({'path':str(f),'bytes':f.stat().st_size,'sha256':sha(f)})
(p/'EVIDENCE_MANIFEST.json').write_text(json.dumps({'published':published,'retained_local_only':retained,'retained_databases':databases,'manifest_excludes_itself':True,'official_assessment_submitted':False},indent=2)+'\n')
print('Published files',len(published),'retained traces',len(retained),'retained database files',len(databases))
