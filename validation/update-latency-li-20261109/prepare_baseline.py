from pathlib import Path
import zipfile,json,hashlib,subprocess,platform,os
repo=Path('/opt/minivectordb-v2'); out=Path(__file__).parent; dest=repo/'build-update-baseline/source'; dest.mkdir(parents=True,exist_ok=False)
hist=repo/'validation/cardinality-20261109'; inventory={}
for name in ['baseline-source-snapshot.zip','baseline-tests-snapshot.zip']:
 with zipfile.ZipFile(hist/name) as z:
  inventory[name]=z.namelist()
  for m in z.infolist():
   target=dest/m.filename
   assert target.resolve().is_relative_to(dest) and not m.is_dir() and not m.filename.startswith('/'),m.filename
   assert (m.external_attr>>16)&0o170000 != 0o120000,m.filename
   data=z.read(m); target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists():assert target.read_bytes()==data
   else:target.write_bytes(data)
manifest=json.loads((hist/'baseline-production-manifest.json').read_text()); checked=[]
for e in manifest['files']:
 data=(dest/e['path']).read_bytes(); assert hashlib.sha256(data).hexdigest()==e['sha256']; checked.append(e['path'])
(out/'baseline-extraction.json').write_text(json.dumps({'archives':inventory,'verified_production_files':checked,'destination':str(dest)},indent=2))
env={'platform':platform.platform(),'cpu_affinity':sorted(os.sched_getaffinity(0)),'python':platform.python_version()}
for name,cmd in [('compiler',['g++','--version']),('cmake',['cmake','--version']),('memory',['free','-h']),('filesystem',['findmnt','-T',str(repo),'-o','SOURCE,FSTYPE,MAJ:MIN']),('disk',['df','-h',str(repo)]),('strace',['strace','--version'])]:env[name]=subprocess.check_output(cmd,text=True)
(out/'environment.json').write_text(json.dumps(env,indent=2))
print('Safe baseline extraction and 12 production hashes verified')
