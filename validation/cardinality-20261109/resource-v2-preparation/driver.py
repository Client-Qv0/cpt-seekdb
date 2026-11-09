import hashlib,importlib.util,io,json,os,pathlib,select,subprocess,sys,tempfile,threading,time,unittest,uuid
ROOT=pathlib.Path('/mnt/c/Users/sunyilun/Documents/Codex/2026-10-26/https-open-oceanbase-com-train-detail/work/minivectordb-round2')
import argparse,shutil
parser=argparse.ArgumentParser(description='Frozen four-case resource regression, actual candidate executable mounted read-only')
parser.add_argument('--binary',type=pathlib.Path,required=True)
parser.add_argument('--expected-binary-sha256',required=True)
parser.add_argument('--source-root',type=pathlib.Path,required=True)
parser.add_argument('--source-manifest',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
def sha256_file(path):
 with pathlib.Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
BINARY=args.binary.resolve()
assert sha256_file(BINARY)==args.expected_binary_sha256,'Candidate binary SHA mismatch before execution'
CANDIDATE_MANIFEST=json.loads(args.source_manifest.read_text())
SOURCE_BINDING={'source_root':str(args.source_root.resolve()),'manifest_path':str(args.source_manifest.resolve()),'manifest_sha256':sha256_file(args.source_manifest),'production_tree_sha256':CANDIDATE_MANIFEST.get('production_tree_sha256',CANDIDATE_MANIFEST.get('tree_sha256')),'verified_files':[]}
for entry in CANDIDATE_MANIFEST['files']:
 path=(args.source_root/entry['path']).resolve()
 assert path.is_relative_to(args.source_root.resolve()),'Manifest path leaves source root'
 assert sha256_file(path)==entry['sha256'],'Frozen candidate source mismatch: '+entry['path']
 SOURCE_BINDING['verified_files'].append({'path':entry['path'],'sha256':entry['sha256']})
OLD_AUDIT=ROOT/'validation/audit-20261109-42affed2e283'
AUDIT=args.output.resolve()
assert not AUDIT.exists() or not any(AUDIT.iterdir()),'Evidence output must be empty'
AUDIT.mkdir(parents=True,exist_ok=True)
assert subprocess.check_output(['findmnt','--noheadings','--output','FSTYPE','--target',str(AUDIT)],text=True).strip()=='ext4','Use WSL ext4 evidence and data'
shutil.copyfile(__file__,AUDIT/'driver.py')
shutil.copyfile(args.source_manifest,AUDIT/'source-manifest.json')

SOURCE=ROOT/'build-audit/audit-20261109-42affed2e283/source'
os.environ['DOCKER_HOST']='unix:///var/tmp/minivectordb-docker/docker.sock'
META=json.loads((OLD_AUDIT/'docker-image.json').read_text()); IMAGE=META['image_id']; LIMIT=128*1024**2
RUNTIME_IMAGE_EMBEDDED_BINARY_SHA=META['container_binary_sha256']
META.update({'audit_id':AUDIT.name,'audit_source_tree_sha256':SOURCE_BINDING['production_tree_sha256'],'audit_source_manifest_sha256':SOURCE_BINDING['manifest_sha256'],'container_binary_sha256':args.expected_binary_sha256})
FROZEN_TEST_HASHES=json.loads((OLD_AUDIT/'docker-resource-regression-harness.json').read_text())['frozen_test_sources']
for relative,expected in FROZEN_TEST_HASHES.items():
 assert sha256_file(SOURCE/relative)==expected,'Original frozen test changed: '+relative
(AUDIT/'preflight.json').write_text(json.dumps({'actual_binary':str(BINARY),'binary_sha256':args.expected_binary_sha256,'source_binding':SOURCE_BINDING,'runtime_image_id':IMAGE,'runtime_image_embedded_binary_sha256_not_executed':RUNTIME_IMAGE_EMBEDDED_BINARY_SHA,'driver_sha256':sha256_file(__file__),'original_driver_sha256':sha256_file(OLD_AUDIT/'docker-resource-regression-driver.txt'),'frozen_test_hashes':FROZEN_TEST_HASHES,'adaptation':'Original four test assertions unchanged. Only executable mount/entrypoint, source and output metadata adapted. Database data under /var/tmp ext4; no image rebuild.'},indent=2)+'\n')
tempfile.tempdir='/var/tmp'

sys.path.insert(0,str(SOURCE/'tests'))
import acceptance as core
import optimization_acceptance as opt
core.STRESS=True; opt.LARGE=True
records=[]; active=[]

def docker(*args,check=True):
 return subprocess.run(['docker',*args],capture_output=True,text=True,check=check)

class Container:
 def __init__(self,directory,stderr,label):
  self.name='mvdb-resource-'+uuid.uuid4().hex
  self.stop=threading.Event(); self.lock=threading.Lock();self.cg=None;self.thread=None
  self.entry={'name':self.name,'label':label,'data_host_directory':str(directory),'snapshots':[],'peak_observed_bytes':0,'sample_errors':[]}
  records.append(self.entry);active.append(self)
  self.proc=subprocess.Popen(['docker','run','--name',self.name,'-i','--network','none','--cpus','2','--memory','128m','--memory-swap','128m','--mount','type=bind,src='+str(pathlib.Path(directory).resolve())+',dst=/data','--mount','type=bind,src='+str(BINARY)+',dst=/probe/minivectordb,readonly','--entrypoint','/probe/minivectordb',IMAGE,'--data-dir','/data','--dev-protocol'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr)
  self.stdin=self.proc.stdin;self.stdout=self.proc.stdout
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   found=docker('inspect',self.name,check=False)
   if found.returncode==0:
    info=json.loads(found.stdout)[0]
    if info['State']['Pid']:
     self.entry.update({'id':info['Id'],'image_id':info['Image'],'host_pid':info['State']['Pid'],'host_config':{k:info['HostConfig'][k] for k in ['Memory','MemorySwap','NanoCpus','NetworkMode']}})
     relative=pathlib.Path(f"/proc/{info['State']['Pid']}/cgroup").read_text().strip().split(':',2)[2]
     self.cg=pathlib.Path('/sys/fs/cgroup')/relative.lstrip('/')
     self.entry['cgroup_path']=str(self.cg)
     self.entry['data_device']=subprocess.check_output(['findmnt','--noheadings','--output','SOURCE,MAJ:MIN,FSTYPE','--target',str(directory)],text=True).strip()
     assert info['Image']==IMAGE and info['HostConfig']['Memory']==LIMIT and info['HostConfig']['MemorySwap']==LIMIT
     initial=self.capture('container_started')
     assert initial and initial['memory.max']==str(LIMIT) and initial['memory.swap.max']=='0' and initial['cpu.max']=='200000 100000'
     self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
     return
   if self.proc.poll() is not None:break
   time.sleep(.03)
  raise RuntimeError('Container failed to become running: '+self.name)
 def snapshot(self):
  if not self.cg:return None
  try:
   value={n:(self.cg/n).read_text().strip() for n in ['memory.peak','memory.current','memory.events','memory.max','memory.swap.max','cpu.max','io.stat']}
   value['time_monotonic']=time.monotonic()
   with self.lock:
    self.entry['last_live_cgroup_snapshot']=value
    self.entry['peak_observed_bytes']=max(self.entry['peak_observed_bytes'],int(value['memory.peak']))
   return value
  except Exception as e:
   with self.lock:
    if len(self.entry['sample_errors'])<4:self.entry['sample_errors'].append(str(e))
   return None
 def capture(self,label):
  value=self.snapshot()
  if value:
   with self.lock:self.entry['snapshots'].append({'phase':label,'values':value})
  return value
 def monitor(self):
  while not self.stop.wait(.1):self.snapshot()
 def poll(self):return self.proc.poll()
 def wait(self,timeout=None):return self.proc.wait(timeout=timeout)
 def kill(self):
  self.capture('before_requested_SIGKILL')
  docker('kill','--signal','KILL',self.name,check=False)
 def finish(self):
  self.capture('before_cleanup')
  self.stop.set()
  if self.thread:self.thread.join(timeout=1)
  found=docker('inspect',self.name,check=False)
  if found.returncode==0:
   state=json.loads(found.stdout)[0]['State']
   self.entry['docker_final_state']={k:state.get(k) for k in ['Status','Running','OOMKilled','ExitCode','Error','StartedAt','FinishedAt']}
  docker('rm','--force',self.name,check=False)
  if self.proc.poll() is None:self.proc.kill();self.proc.wait(timeout=5)
  if self in active:active.remove(self)

class ContainerDatabase(core.Database):
 def __init__(self,directory,memory_limit=None):
  self.directory=pathlib.Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
  self.stderr=tempfile.TemporaryFile(mode='w+b')
  self.proc=Container(self.directory,self.stderr,'storage/setup/restart')
  self.proc.entry['requested_host_RLIMIT_AS_ignored']=memory_limit
  self.proc.entry['limiting_mechanism']='actual container cgroup memory.max; no outer driver RLIMIT_AS used'
 def close(self,kill=False):
  try:
   self.proc.capture('before_Database_close')
   super().close(kill=kill)
  finally:self.proc.finish()
core.Database=ContainerDatabase

class ContainerLargeResponses(opt.LargeResponseAcceptance):
 def run_streaming_query(self,sql,callback):
  with tempfile.TemporaryFile(mode='w+b') as output,tempfile.TemporaryFile(mode='w+b') as errors:
   proc=Container(self.directory,errors,self.id())
   try:
    proc.stdin.write((sql+'\n').encode());proc.stdin.flush()
    deadline=time.monotonic()+120
    complete=False;size=0
    while not complete:
     remaining=deadline-time.monotonic()
     if remaining<=0:raise AssertionError('Container output timeout at 120s')
     ready,_,_=select.select([proc.stdout],[],[],min(1,remaining))
     if not ready:
      if proc.poll() is not None:break
      continue
     chunk=os.read(proc.stdout.fileno(),65536)
     if not chunk:break
     output.write(chunk);size+=len(chunk)
     if b'\n' in chunk:
      self.assertTrue(chunk.endswith(b'\n'),'Unexpected trailing bytes after response newline')
      complete=True
    proc.entry['output_bytes']=size
    proc.capture('after_full_response_before_EOF')
    if proc.stdin and not proc.stdin.closed:proc.stdin.close()
    returncode=proc.wait(timeout=15)
    errors.seek(0)
    self.assertEqual(returncode,0,errors.read().decode('utf-8',errors='replace'))
    self.assertTrue(complete,'Output ended before complete response newline')
    output.seek(0)
    reader=io.TextIOWrapper(output,encoding='utf-8')
    try:fields,count=opt.JsonStream(reader).response(callback)
    finally:reader.detach()
    proc.entry['verified_result_rows']=count
    return fields,count,size
   finally:
    if proc.poll() is None:proc.kill()
    proc.finish()

suite=unittest.TestSuite()
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ContainerLargeResponses))
suite.addTest(core.Acceptance('test_19_disk_data_larger_than_address_space'))
result=None
try:
 with (AUDIT/'docker-resource-regression-log.txt').open('w') as log:
  log.write('Frozen source/image. Docker cgroup memory.max=134217728, memory.swap.max=0, cpu.max=200000 100000.\n')
  log.write('Original frozen test assertions; only database process creation/stream transport adapted.\n')
  result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
finally:
 for container in list(active):container.finish()
 summary={'audit_id':META['audit_id'],'source_tree_sha256':META['audit_source_tree_sha256'],'source_manifest_sha256':META['audit_source_manifest_sha256'],'image_id':IMAGE,'binary_sha256':META['container_binary_sha256'],'tests_run':result.testsRun if result else None,'failures':len(result.failures) if result else None,'errors':len(result.errors) if result else None,'skipped':len(result.skipped) if result else None,'success':result.wasSuccessful() if result else False,'memory_max':LIMIT,'memory_swap_max':0,'cpu_max':'200000 100000','network':'none','driver_RLIMIT_AS_not_used':True,'official_benchmark':False,'containers':records,'limits':['These are four resource regression cases, not the official benchmark.','io.stat values are observations from the actual container cgroup on shared WSL /dev/sdd; dedicated-device and writeback-attribution calibration are unverified.','Driver output files and parsing live outside the container, consistent with separating test-driver overhead.','For any unexpected exit, exact final cgroup counters may be unavailable; last live sample and Docker OOMKilled state are preserved explicitly.']}
 summary['actual_executable_binding']={'binary_path':str(BINARY),'sha256_before':args.expected_binary_sha256,'sha256_after':sha256_file(BINARY),'read_only_bind_mount':True,'entrypoint':'/probe/minivectordb','runtime_image_embedded_binary_sha256_not_executed':RUNTIME_IMAGE_EMBEDDED_BINARY_SHA}
 summary['source_binding']=SOURCE_BINDING
 summary['source_unchanged_after']=all(sha256_file(args.source_root/entry['path'])==entry['sha256'] for entry in CANDIDATE_MANIFEST['files']) and sha256_file(args.source_manifest)==SOURCE_BINDING['manifest_sha256']
 summary['binary_unchanged_after']=sha256_file(BINARY)==args.expected_binary_sha256
 summary['success']=summary['success'] and summary['source_unchanged_after'] and summary['binary_unchanged_after']
 (AUDIT/'docker-resource-regression-results.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps({k:v for k,v in summary.items() if k!='containers'},indent=2),flush=True)
 print('CONTAINER_RESOURCE_SUMMARY',json.dumps([{'label':v['label'],'peak':v['peak_observed_bytes'],'rows':v.get('verified_result_rows'),'output_bytes':v.get('output_bytes'),'state':v.get('docker_final_state')} for v in records]),flush=True)
raise SystemExit(0 if result and result.wasSuccessful() and summary['success'] else 1)
