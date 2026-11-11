import pathlib,json,hashlib,subprocess,os,shutil,fcntl,statistics
R=pathlib.Path(__file__).resolve().parent
T=pathlib.Path('/var/tmp/minivectordb-c4-20261111')
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
rows=[json.loads(x) for x in (R/'aa1/runner.stdout.log').read_text().splitlines() if x.startswith('{')]
pairs={}
for x in rows:pairs.setdefault(x['round'],{})[x['label']]=x
diff=[abs(x['B']['times']['query_s']/x['A']['times']['query_s']-1) for x in pairs.values()]
aa={'pairs':len(pairs),'absolute_relative_query_difference':diff,'median':statistics.median(diff),'max':max(diff),'formula':'abs(B.query_s/A.query_s-1)','pass':len(diff)==6 and statistics.median(diff)<=.03 and max(diff)<=.10}
(R/'aa1-summary.json').write_text(json.dumps(aa,indent=2)+'\n')
assert aa['pass'],aa
print('AA_PASS '+json.dumps(aa),flush=True)
def run(args,name,timeout=600):
 (R/'runtime'/f'{name}-command.json').write_text(json.dumps(args,indent=2))
 with (R/'runtime'/f'{name}.log').open('wb') as log:
  p=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 assert p.returncode==0,(name,p.returncode)
def docker(args):return subprocess.check_output(['docker',*map(str,args)],env=env,timeout=90)
assert not docker(['ps','-q']).strip()
context=T/'candidate-source';context.mkdir()
for f in json.loads((R/'candidate-manifest.json').read_text()):
 raw=(R/'candidate'/f['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==f['sha256']
 if f['path'].startswith(('src/','tests/')) or f['path'] in ['Dockerfile','CMakeLists.txt','.dockerignore']:
  out=context/f['path'];out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(raw)
run(['docker','build','--network','host','-t','minivectordb:c4-scalar-loads',str(context)],'candidate-build')
inspect=json.loads(docker(['image','inspect','minivectordb:c4-scalar-loads']))
(R/'runtime/candidate-image.json').write_text(json.dumps(inspect,indent=2))
name='c4-export';docker(['create','--name',name,inspect[0]['Id']])
try:docker(['cp',name+':/app/minivectordb',str(T/'candidate-minivectordb')])
finally:docker(['rm',name])
shutil.copyfile(T/'candidate-minivectordb',R/'runtime/candidate-minivectordb')
shutil.copyfile(R.parent/'minivectordb-c3-material-20261111/runtime/baseline-minivectordb',T/'baseline-minivectordb')
os.chmod(T/'baseline-minivectordb',0o755)
assert hashlib.sha256((T/'baseline-minivectordb').read_bytes()).hexdigest()=='b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67'
binary_sha=hashlib.sha256((T/'candidate-minivectordb').read_bytes()).hexdigest()
(R/'runtime/candidate-binary.json').write_text(json.dumps({'sha256':binary_sha,'image':inspect[0]['Id'],'base_commit':'87c2778ed0688e6e56152baf02bc4f4355667458','candidate_manifest_sha256':hashlib.sha256((R/'candidate-manifest.json').read_bytes()).hexdigest()},indent=2))
mount=['--mount',f'type=bind,src={T},dst=/c4']
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','cmake','-S','/c4/candidate-source','-B','/c4/release-tests','-DCMAKE_BUILD_TYPE=Release'],'test-cmake')
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','cmake','--build','/c4/release-tests','--parallel','2'],'test-build')
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','ctest','--test-dir','/c4/release-tests','--output-on-failure'],'ctest-release')
assert hashlib.sha256((T/'release-tests/minivectordb').read_bytes()).hexdigest()==binary_sha,'Test build differs from production image binary'
asm=docker(['run','--rm','--network','none',*mount,'minivectordb:c4-builder','objdump','-d','-C','/c4/candidate-minivectordb'])
(R/'runtime/candidate.asm').write_bytes(asm)
(R/'runtime/cpuinfo.txt').write_bytes(pathlib.Path('/proc/cpuinfo').read_bytes())
print('CANDIDATE_BUILT '+binary_sha+' '+inspect[0]['Id'],flush=True)
