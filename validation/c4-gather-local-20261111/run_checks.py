import pathlib,subprocess,os,json,hashlib,fcntl,re
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c4-20261111')
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
O=R/'checks';O.mkdir()
def run(args,name,timeout=300):
 (O/(name+'-command.json')).write_text(json.dumps(list(map(str,args)),indent=2))
 with (O/(name+'.stdout.log')).open('wb') as out,(O/(name+'.stderr.log')).open('wb') as err:
  p=subprocess.run(list(map(str,args)),env=env,stdout=out,stderr=err,timeout=timeout)
 (O/(name+'-exit.json')).write_text(json.dumps({'exit_code':p.returncode}))
 assert p.returncode==0,name
 print(name+' PASS',flush=True)
source='#include "exact_cache.hpp"\n#include <iostream>\nint main(){std::cout << "mvdb::exact::available=" << mvdb::exact::available() << "\\n";return mvdb::exact::available()?0:1;}\n'
(T/'cpu_dispatch.cpp').write_text(source);(O/'cpu_dispatch.cpp').write_text(source)
mount=['--mount',f'type=bind,src={T},dst=/c4']
run(['docker','run','--rm','--network','none',*mount,'minivectordb:c4-builder','g++','-std=c++17','-O3','-I/c4/candidate-source/src','/c4/cpu_dispatch.cpp','-o','/c4/cpu_dispatch'],'cpu-probe-build')
run(['docker','run','--rm','--network','none','--read-only','--cpuset-cpus','0,1',*mount,'minivectordb:c4-builder','/c4/cpu_dispatch'],'cpu-probe')
asm=(R/'runtime/candidate.asm').read_text()
blocks=re.split(r'(?m)^(?=[0-9a-f]+ <)',asm)
kernel=[x for x in blocks if 'distances4_avx2(' in x.splitlines()[0]]
assert len(kernel)==1
block=kernel[0];assert 'vgather' not in block and not re.search(r'\bv(?:f|fn)m(?:add|sub)',block)
assert all(x in block for x in ['vmulpd','vaddpd','vsqrtpd'])
assert re.search(r'call\s+\S+\s+<mvdb::exact::distances4_avx2',asm)
(O/'actual-candidate-avx2.asm').write_text(block)
(O/'assembly-audit.json').write_text(json.dumps({'binary_sha256':hashlib.sha256((T/'candidate-minivectordb').read_bytes()).hexdigest(),'actual_production_binary':True,'avx2_kernel_present':True,'caller_present':True,'gather_present':False,'fma_present':False,'separate_double_multiply_add_sqrt':True,'dispatch_evidence':'cpu-probe.stdout.log; test_exact_cache automatic dispatcher on this AVX2 host'},indent=2))
tests=R/'candidate/tests';B=T/'baseline-minivectordb';C=T/'candidate-minivectordb'
run(['python3',tests/'distance_differential.py','--baseline',B,'--candidate',C,'--output',O/'distance-result.json'],'distance-differential')
run(['python3',tests/'test_formal_stdio.py','--baseline',B,'--candidate',C,'--output',O/'formal'],'formal-stdio')
run(['python3',tests/'acceptance.py','--binary',C],'acceptance')
run(['python3',tests/'optimization_acceptance.py','--binary',C],'optimization-acceptance')
print('BASIC_CHECKS_COMPLETE',flush=True)
