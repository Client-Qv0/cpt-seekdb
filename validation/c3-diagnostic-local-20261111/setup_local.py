import pathlib, subprocess, json, time, os, hashlib, shutil, fcntl
R=pathlib.Path(__file__).resolve().parent
T=pathlib.Path('/var/tmp/minivectordb-c3-20261111')
T.mkdir(exist_ok=True)
L=R/'runtime';L.mkdir(exist_ok=True)
existing=subprocess.run(['pgrep','-x','dockerd'],capture_output=True,text=True)
sock=T/'docker.sock'
if existing.returncode!=0:
 (T/'daemon.json').write_text('{"features":{"containerd-snapshotter":false}}\n')
 with (L/'dockerd.log').open('ab') as log:
  p=subprocess.Popen(['dockerd','--config-file',str(T/'daemon.json'),'--data-root','/var/tmp/minivectordb-docker/data','--exec-root',str(T/'exec'),'--pidfile',str(T/'dockerd.pid'),'--host','unix://'+str(sock),'--bridge=none','--iptables=false','--ip6tables=false','--ip-forward=false','--ip-masq=false','--storage-driver=vfs'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
env=dict(os.environ,DOCKER_HOST='unix://'+str(sock))
def docker(args,timeout=60):
 p=subprocess.run(['docker',*args],env=env,capture_output=True,timeout=timeout)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
 return p.stdout
for i in range(20):
 try: info=docker(['info','--format','{{json .}}']);break
 except Exception:
  if i==19:raise
  time.sleep(1)
(L/'docker-info.json').write_bytes(info)
(L/'containers-before.json').write_bytes(docker(['ps','--format','{{json .}}']))
assert not docker(['ps','-q']).strip(),'Other containers active: do not benchmark'
(L/'cpuinfo.txt').write_text(pathlib.Path('/proc/cpuinfo').read_text())
(L/'host.json').write_text(json.dumps({'local_reproduction':True,'uname':subprocess.check_output(['uname','-a']).decode(),'docker_host':env['DOCKER_HOST'],'avx2':'avx2' in pathlib.Path('/proc/cpuinfo').read_text()},indent=2))
context=T/'baseline-source'; context.mkdir(exist_ok=True)
manifest=json.loads((R/'inputs/source-manifest.json').read_text())
for e in manifest['files']:
 n=e['path']
 if n.startswith(('src/','tests/')) or n in ['CMakeLists.txt','Dockerfile','.dockerignore']:
  source=R/'baseline'/n; raw=source.read_bytes()
  assert hashlib.sha256(raw).hexdigest()==e['sha256'],n
  dest=context/n;dest.parent.mkdir(exist_ok=True,parents=True);dest.write_bytes(raw)
with (L/'baseline-build.log').open('wb') as log:
 p=subprocess.run(['docker','build','-t','minivectordb:c3-baseline-87c2','.'],cwd=context,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
assert p.returncode==0,'Docker build failed; see log'
(L/'baseline-image.json').write_bytes(docker(['image','inspect','minivectordb:c3-baseline-87c2']))
name='mvdb-c3-baseline-export'
docker(['create','--name',name,'minivectordb:c3-baseline-87c2'])
try:docker(['cp',name+':/app/minivectordb',str(L/'baseline-minivectordb')])
finally:docker(['rm',name])
(L/'baseline-binary.json').write_text(json.dumps({'commit':manifest['commit'],'sha256':hashlib.sha256((L/'baseline-minivectordb').read_bytes()).hexdigest(),'local_rebuild':True},indent=2))
print('LOCAL_BASELINE_READY',flush=True)
