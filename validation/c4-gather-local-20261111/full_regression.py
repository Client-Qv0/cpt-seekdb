import pathlib,subprocess,os,json,hashlib,fcntl,shutil
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c4-20261111')
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not (R/'PERFORMANCE_STOP.json').exists()
assert (R/'overflow-summary.json').is_file()
O=R/'full-regression';O.mkdir()
image=json.loads((R/'runtime/candidate-image.json').read_text())[0]['Id']
def run(args,name,timeout=600,environment=None):
 (O/(name+'-command.json')).write_text(json.dumps(list(map(str,args)),indent=2))
 with (O/(name+'.stdout.log')).open('wb') as out,(O/(name+'.stderr.log')).open('wb') as err:
  p=subprocess.run(list(map(str,args)),env=environment or env,stdout=out,stderr=err,timeout=timeout)
 (O/(name+'-exit.json')).write_text(json.dumps({'exit_code':p.returncode}))
 assert p.returncode==0,name
 print(name+' PASS',flush=True)
official=R.parent/'minivectordb-protocol-20261110-f4d4e266/official'
files=[]
for p in sorted(official.rglob('*')):
 if p.is_file() and '__pycache__' not in p.parts:
  files.append({'path':p.relative_to(official).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(O/'official-tool-manifest.json').write_text(json.dumps({'commit':'f4d4e26653af823a7601668802f80e374ad6643c','files':files,'config_unchanged':True},indent=2))
for name,flags in [('official-handshake',['--handshake-only']),('official-crud',['--case','sql_crud']),('official-public',[])]:
 run(['python3',official/'protocol_check/run.py','--image',image,*flags,'--output',O/name],name,1200)
tests=R/'candidate/tests';C=T/'candidate-minivectordb'
run(['python3',tests/'test_container_recovery.py','--image',image,'--data-root',T/'full-recovery-data','--output',O/'recovery'],'docker-recovery')
run(['python3',tests/'acceptance.py','--binary',C,'--stress'],'acceptance-stress')
run(['python3',tests/'optimization_acceptance.py','--binary',C,'--large'],'optimization-large')
run(['python3','-m','unittest','discover','-s',tests,'-p','test_benchmark_public_validation.py'],'benchmark-tool-tests')
mount=['--mount',f'type=bind,src={T},dst=/c4']
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','cmake','-S','/c4/candidate-source','-B','/c4/sanitizer-tests','-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer','-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined'],'sanitizer-cmake')
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','cmake','--build','/c4/sanitizer-tests','--parallel','2'],'sanitizer-build')
run(['docker','run','--rm','--network','none','-e','ASAN_OPTIONS=detect_leaks=1:halt_on_error=1','-e','UBSAN_OPTIONS=halt_on_error=1',*mount,'minivectordb:c4-builder','ctest','--test-dir','/c4/sanitizer-tests','--output-on-failure'],'sanitizer-ctest')
sanenv=dict(env,ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
run(['python3',tests/'distance_differential.py','--baseline',T/'baseline-minivectordb','--candidate',T/'sanitizer-tests/minivectordb','--output',O/'sanitizer-distance.json'],'sanitizer-distance',environment=sanenv)
run(['python3',R/'tests/sql_lane_edges.py','--baseline',T/'baseline-minivectordb','--candidate',T/'sanitizer-tests/minivectordb','--output',T/'sanitizer-lane-edges'],'sanitizer-lanes',environment=sanenv)
shutil.copytree(T/'sanitizer-lane-edges',O/'sanitizer-lane-edges',ignore=shutil.ignore_patterns('data'))
(O/'sanitizer-binary.json').write_text(json.dumps({'sha256':hashlib.sha256((T/'sanitizer-tests/minivectordb').read_bytes()).hexdigest(),'build':'Debug ASan+UBSan; not benchmarked'},indent=2))
print('FULL_REGRESSION_PASS',flush=True)
