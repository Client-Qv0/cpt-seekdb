import pathlib,json,hashlib,subprocess,os,shutil,fcntl
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c4-20261111');T.mkdir(exist_ok=False)
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def docker(args,timeout=90):return subprocess.check_output(['docker',*map(str,args)],env=env,timeout=timeout)
assert not docker(['ps','-q']).strip()
m=json.loads((R/'inputs/source-manifest.json').read_text())
context=T/'baseline-source';context.mkdir()
for f in m['files']:
 raw=(R/'baseline'/f['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==f['sha256']
 if f['path'].startswith(('src/','tests/')) or f['path'] in ['CMakeLists.txt','Dockerfile','.dockerignore']:
  d=context/f['path'];d.parent.mkdir(exist_ok=True,parents=True);d.write_bytes(raw)
with (R/'runtime/builder.log').open('wb') as log:
 p=subprocess.run(['docker','build','--network','host','--target','builder','-t','minivectordb:c4-builder',str(context)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
assert p.returncode==0
shutil.copyfile(R/'micro.cpp',T/'micro.cpp')
cmd=['run','--rm','--network','none','--mount',f'type=bind,src={T},dst=/c4','minivectordb:c4-builder','g++','-std=c++17','-O3','-DNDEBUG','-ffp-contract=off','-I/c4/baseline-source/src','/c4/micro.cpp','-o','/c4/micro']
(R/'runtime/micro-build-command.json').write_text(json.dumps(cmd,indent=2))
with (R/'runtime/micro-build.log').open('wb') as log:
 p=subprocess.run(['docker',*cmd],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120)
assert p.returncode==0
shutil.copyfile(T/'micro',R/'runtime/micro')
asm=docker(['run','--rm','--network','none','--mount',f'type=bind,src={T},dst=/c4,readonly','minivectordb:c4-builder','objdump','-d','-C','/c4/micro'])
(R/'runtime/micro.asm').write_bytes(asm)
cmd=['run','--rm','--network','none','--read-only','--memory','128m','--memory-swap','128m','--cpus','2','--cpuset-cpus','0,1','--mount',f'type=bind,src={T},dst=/c4,readonly','minivectordb:c4-builder','/c4/micro']
with (R/'runtime/micro.stdout.jsonl').open('wb') as out,(R/'runtime/micro.stderr.log').open('wb') as err:
 p=subprocess.run(['docker',*cmd],env=env,stdout=out,stderr=err,timeout=180)
assert p.returncode==0
print('MICRO_COMPLETE',flush=True)
bench=R/'baseline/validation/perf-20261110-stdio/scripts/bench_portable.py'
base='sha256:4dcb69128fbea4448e1dc4b0b37c5412ce788290a4fa410b1d976c1fc002de74'
command=['/var/tmp/minivectordb-paired-venv/bin/python',str(bench),'--images','A='+base,'B='+base,'--output-root',str(R/'aa1'),'--data-root',str(T/'aa1-data'),'--docker-host',env['DOCKER_HOST'],'--prefix','c4aa1','--seeds','3179','3181','3187','3179','3181','3187','--rows','10000','--dim','128','--queries','1000']
(R/'runtime/aa1-command.json').write_text(json.dumps(command,indent=2))
p=subprocess.run(command,env=env);assert p.returncode==0
print('AA1_COMPLETE',flush=True)
