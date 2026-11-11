import concurrent.futures,hashlib,json,os,pathlib,subprocess,urllib.request
R=pathlib.Path(__file__).resolve().parent
BASE='87c2778ed0688e6e56152baf02bc4f4355667458'
SHARED='ef2cece289850201576c6dc7da1db58ef5a99bad'
URL='https://github.com/Client-Qv0/cpt-seekdb.git'
STORE=R/'repository.git'
ENV=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
def git(args):
 p=subprocess.run(['git','-c','credential.username=smikey12','-c','http.version=HTTP/1.1','--git-dir',str(STORE),*args],env=ENV,capture_output=True,timeout=120)
 assert p.returncode==0,p.stderr.decode(errors='replace')
 return p.stdout.decode().strip()
if not STORE.exists():
 subprocess.run(['git','init','--bare',str(STORE)],check=True,capture_output=True)
 git(['remote','add','origin',URL]);git(['config','remote.origin.promisor','true']);git(['config','remote.origin.partialclonefilter','blob:none'])
git(['cat-file','-e',BASE+'^{commit}'])
tree=git(['ls-tree','-r',BASE]);(R/'inputs/baseline-tree.txt').write_text(tree+'\n')
entries={line.split('\t',1)[1]:line.split()[2] for line in tree.splitlines()}
paths=[p for p in entries if p.endswith('AGENTS.md') or p.startswith(('src/','tests/','validation/perf-20261110-stdio/scripts/')) or (p.startswith(('validation/exact-scan-li-20261110/','validation/cache-amortization-li-20261111/')) and p.endswith(('.md','.py'))) or p in ['agent/conversation.json','CMakeLists.txt','Dockerfile','.dockerignore','README.md','conversation.json']]
def fetch(name):
 url=f'https://raw.githubusercontent.com/Client-Qv0/cpt-seekdb/{BASE}/{name}'
 dest=R/'baseline'/name
 raw=dest.read_bytes() if dest.exists() else None
 if raw is None:
  with urllib.request.urlopen(url,timeout=45) as response:raw=response.read()
 oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 assert oid==entries[name],name
 dest.parent.mkdir(parents=True,exist_ok=True)
 if not dest.exists():dest.write_bytes(raw)
 return {'path':name,'git_blob':oid,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:files=list(pool.map(fetch,paths))
manifest={'commit':BASE,'tree':git(['rev-parse',BASE+'^{tree}']),'shared':SHARED,'files':files,'AGENTS_paths':[p for p in entries if p.endswith('AGENTS.md')],'not_full_repository_export':True}
(R/'inputs/source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'downloaded':len(files),'bytes':sum(x['bytes'] for x in files),'AGENTS_paths':manifest['AGENTS_paths'],'tree':manifest['tree']}))

