from pathlib import Path
import json,hashlib,shutil,subprocess,sys,re
p=Path(__file__).parent; repo=p.parents[1]
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
files=[{'path':str(f.relative_to(repo)),'sha256':sha(f),'bytes':f.stat().st_size} for f in sorted((repo/'src').glob('*')) if f.is_file()]
for n in ['CMakeLists.txt','Dockerfile','.dockerignore']:files.append({'path':n,'sha256':sha(repo/n),'bytes':(repo/n).stat().st_size})
tree=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest();(p/'candidate-production-manifest.json').write_text(json.dumps({'files':files,'production_tree_sha256':tree,'tree_sha256':tree,'note':'Final retrospective source binding; raw run manifest null fields unchanged.'},indent=2)+'\n')
shutil.copyfile('/opt/minivectordb-v2/validation/update-latency-li-20261109/resource_driver.py',p/'resource_driver.py')
s=subprocess.check_output([sys.executable,str(p/'resume_finalize.py')],text=True);results={}
for line in s.splitlines():
 if not line.startswith('million-'):continue
 assert 'False' not in line
 name=line.split()[0]; a=int(re.search(r'anonMax (\d+)',line)[1]); peak=int(re.search(r'peakMax (\d+)',line)[1]);oom=int(re.search(r'oomKillMax (\d+)',line)[1]);assert a>0 and peak<=134217728 and oom==0
 d=json.loads((p/name).read_text());results[name]={'anon_max':a,'memory_peak':peak,'oom_kill_max':oom,'passed':True,'raw_sha256':sha(p/name),'binary_sha256':d['binary_sha256'],'raw_source_manifest_sha256':d.get('source_manifest_sha256')}
assert len(results)==4
for a,b in [('million-baseline','million-c2'),('million-vector-baseline','million-vector-c2')]:
 ratio=results[b]['anon_max']/results[a]['anon_max'];assert ratio<=1.05;results[b]['anon_over_baseline']=ratio
(p/'MILLION_GATE.json').write_text(json.dumps({'passed':True,'runs':results,'scope':'One independent case per schema/version; sampled anon maxima and kernel memory.peak, not latency distribution. Raw source_manifest_sha256 stays null; source binding separately checked.'},indent=2)+'\n');print('Million gate PASS, production inputs',len(files))
