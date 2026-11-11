import pathlib,json,os,subprocess,hashlib,shutil,fcntl,re
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c6-contiguous-20261111');T.mkdir()
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
L=R/'runtime';L.mkdir()
def run(args,name,timeout=600):
 (L/(name+'-command.json')).write_text(json.dumps(list(map(str,args)),indent=2))
 with (L/(name+'.stdout.log')).open('wb') as out,(L/(name+'.stderr.log')).open('wb') as err:
  p=subprocess.run(list(map(str,args)),env=env,stdout=out,stderr=err,timeout=timeout)
 (L/(name+'-exit.json')).write_text(json.dumps({'exit_code':p.returncode}));assert p.returncode==0,name
 print(name+' PASS',flush=True)
def docker(args):return subprocess.check_output(['docker',*map(str,args)],env=env,timeout=90)
assert not docker(['ps','-q']).strip()
source=T/'source';source.mkdir()
for f in json.loads((R/'candidate-manifest.json').read_text()):
 raw=(R/'candidate'/f['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==f['sha256'];p=source/f['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
run(['docker','build','--network','host','-t','minivectordb:c6-contiguous',source],'image-build')
info=json.loads(docker(['image','inspect','minivectordb:c6-contiguous']));(L/'image.json').write_text(json.dumps(info,indent=2))
name='c6-contiguous-export';docker(['create','--name',name,info[0]['Id']])
try:docker(['cp',name+':/app/minivectordb',str(T/'candidate-minivectordb')])
finally:docker(['rm',name])
shutil.copyfile(T/'candidate-minivectordb',L/'candidate-minivectordb')
shutil.copyfile('/var/tmp/minivectordb-c5-batch8-20261111/candidate-minivectordb',T/'baseline-minivectordb');os.chmod(T/'baseline-minivectordb',0o755)
binding={'production_commit':'17092b6a2e8920cbf699263a1828c22f6628e7b8','baseline_sha256':hashlib.sha256((T/'baseline-minivectordb').read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256((T/'candidate-minivectordb').read_bytes()).hexdigest(),'image':info[0]['Id'],'candidate_manifest_sha256':hashlib.sha256((R/'candidate-manifest.json').read_bytes()).hexdigest()}
assert binding['baseline_sha256']=='d89eb85d97764be0239b6a6c9de56182f3f42659d682001681ccf6a8ec053a31'
(L/'binding.json').write_text(json.dumps(binding,indent=2))
mount=['--mount',f'type=bind,src={T},dst=/c5']
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','g++','-std=c++17','-O3','-DNDEBUG','-I/c5/source/src','/c5/source/tests/test_exact_cache.cpp','-o','/c5/test_exact_cache'],'kernel-test-build')
run(['docker','run','--rm','--network','none','--cpuset-cpus','0,1',*mount,'minivectordb:c4-builder','/c5/test_exact_cache'],'kernel-test')
asm=docker(['run','--rm','--network','none',*mount,'minivectordb:c4-builder','objdump','-d','-C','/c5/candidate-minivectordb']).decode()
(L/'candidate.asm').write_text(asm)
blocks=re.split(r'(?m)^(?=[0-9a-f]+ <)',asm);kernels=[b for b in blocks if 'distances8_contiguous_avx2(' in b.splitlines()[0]];assert len(kernels)==1
kernel=kernels[0];assert not re.search(r'\bv(?:f|fn)m(?:add|sub)',kernel);assert 'vgatherdps' not in kernel and all(i in kernel for i in ['vmulpd','vaddpd','vsqrtpd'])
(L/'kernel8.asm').write_text(kernel)
(L/'assembly-check.json').write_text(json.dumps({'actual_candidate':binding['candidate_sha256'],'contiguous_no_gather':True,'no_fma':True,'mul_add_sqrt':True,'cpu_avx2':'avx2' in pathlib.Path('/proc/cpuinfo').read_text()},indent=2))
run(['python3',R/'tests/sql_batch8_edges.py','--baseline',T/'baseline-minivectordb','--candidate',T/'candidate-minivectordb','--output',T/'sql-batch8'],'sql-batch8',300)
shutil.copytree(T/'sql-batch8',R/'checks-sql-batch8',ignore=shutil.ignore_patterns('data'))
print('C5_BUILD_FOCUSED_CHECKS_PASS '+json.dumps(binding),flush=True)
