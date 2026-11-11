import pathlib,json,subprocess,os,fcntl,tempfile,shutil
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c4-20261111')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
O=R/'checks-ext4';O.mkdir()
probe=[]
for directory in [R/'checks',T]:
 fd,path=tempfile.mkstemp(dir=directory)
 try:
  os.write(fd,b'probe');os.unlink(path)
  try:os.ftruncate(fd,0);result={'ok':True}
  except OSError as e:result={'ok':False,'errno':e.errno,'message':str(e)}
  probe.append({'directory':str(directory),'operation':'mkstemp,write,unlink,ftruncate(fd,0)','result':result})
 finally:os.close(fd)
(O/'filesystem-probe.json').write_text(json.dumps(probe,indent=2))
def run(args,name,timeout=300):
 (O/(name+'-command.json')).write_text(json.dumps(list(map(str,args)),indent=2))
 with (O/(name+'.stdout.log')).open('wb') as out,(O/(name+'.stderr.log')).open('wb') as err:
  p=subprocess.run(list(map(str,args)),stdout=out,stderr=err,timeout=timeout)
 (O/(name+'-exit.json')).write_text(json.dumps({'exit_code':p.returncode}))
 assert p.returncode==0,name
 print(name+' PASS',flush=True)
tests=R/'candidate/tests';B=T/'baseline-minivectordb';C=T/'candidate-minivectordb'
run(['python3',tests/'test_formal_stdio.py','--baseline',B,'--candidate',C,'--output',T/'formal-ext4'],'formal-stdio')
shutil.copytree(T/'formal-ext4',O/'formal',ignore=shutil.ignore_patterns('data','empty-data'))
run(['python3',tests/'acceptance.py','--binary',C],'acceptance')
run(['python3',tests/'optimization_acceptance.py','--binary',C],'optimization-acceptance')
print('BASIC_CHECKS_EXT4_COMPLETE',flush=True)
