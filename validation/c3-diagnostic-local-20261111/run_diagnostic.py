import pathlib,os,subprocess,json,hashlib,fcntl,shutil
R=pathlib.Path(__file__).resolve().parent
T=pathlib.Path('/var/tmp/minivectordb-c3-20261111')
env=dict(os.environ,DOCKER_HOST='unix://'+str(T/'docker.sock'))
lock=open('/var/tmp/minivectordb-benchmark.lock','a+')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def docker(*args):return subprocess.check_output(['docker',*args],env=env,timeout=120)
assert not docker('ps','-q').strip(),'Other containers running'
images={}
for label in ['baseline','instrumented']:
 tag='minivectordb:c3-'+label+'-87c2'
 info=json.loads(docker('image','inspect',tag))[0]
 (R/'runtime'/f'{label}-image.json').write_text(json.dumps(info,indent=2))
 name='mvdb-c3-export-'+label
 docker('create','--name',name,tag)
 try:docker('cp',name+':/app/minivectordb',str(R/'runtime'/(label+'-minivectordb')))
 finally:docker('rm','-v',name)
 binary=R/'runtime'/(label+'-minivectordb')
 images[label]={'image_id':info['Id'],'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
(R/'runtime/tested-images.json').write_text(json.dumps(images,indent=2))
bench=R/'baseline/validation/perf-20261110-stdio/scripts/bench_portable.py'
out=R/'diagnostic-runs'
command=['/var/tmp/minivectordb-paired-venv/bin/python',str(bench),'--images',*[k+'='+v['image_id'] for k,v in images.items()],'--output-root',str(out),'--data-root',str(T/'diagnostic-data'),'--docker-host',env['DOCKER_HOST'],'--prefix','c3stage','--seeds','3179','3181','3187','3179','3181','3187','--rows','10000','--dim','128','--queries','1000']
(R/'runtime/diagnostic-command.json').write_text(json.dumps(command,indent=2))
p=subprocess.run(command,env=env)
assert p.returncode==0,'diagnostic bench failed; evidence retained'
shutil.copyfile(T/'baseline-build-host.log',R/'runtime/baseline-build-host.log')
print('SIX_DIAGNOSTIC_ROUNDS_COMPLETE',flush=True)
