#!/usr/bin/env python3
"""Separate diagnostic only: replay the complete historical prefix; trace UPDATE/SELECT.
Never uses a recovered final WAL as a substitute for the original write history.
"""
import argparse,importlib.util,json,time,subprocess,os,select,gzip,hashlib
from pathlib import Path

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def split_query(c,sql):
 t0=time.perf_counter_ns(); data=memoryview((sql+'\n').encode())
 while data:
  if not select.select([], [c.proc.stdin], [], 60)[1]:raise TimeoutError('send')
  try:data=data[os.write(c.proc.stdin.fileno(),data):]
  except BlockingIOError:pass
 t1=time.perf_counter_ns()
 while b'\n' not in c.pending:
  if not select.select([c.proc.stdout],[],[],60)[0]:raise TimeoutError('response')
  try:chunk=os.read(c.proc.stdout.fileno(),65536)
  except BlockingIOError:continue
  if not chunk:raise RuntimeError('EOF')
  c.pending.extend(chunk)
 t2=time.perf_counter_ns(); line,_,tail=c.pending.partition(b'\n'); c.pending=bytearray(tail); result=json.loads(line); t3=time.perf_counter_ns(); assert result.get('ok') is True,result
 return result,{'send_ns':t1-t0,'wait_read_ns':t2-t1,'parse_consume_ns':t3-t2,'total_ns':t3-t0,'response_bytes':len(line)+1}

def main():
 p=argparse.ArgumentParser(); p.add_argument('--repo',type=Path,default=Path('/opt/minivectordb-v2')); p.add_argument('--binary',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--kind',default='vector4'); p.add_argument('--image',required=True); p.add_argument('--trace',action='store_true'); a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=False)
 hist=a.repo/'validation/cardinality-20261109/paired-candidate-v2'; b=module('paired',hist/'tools/paired_benchmark.py'); ad=module('adapter',hist/'tools/cardinality_probe.py'); workload=b.prepare_cardinality_workload(a.kind,1000000,1000,25000)
 generated=''.join(cmd['sql']+'\n' for _,cmds in workload['stages']+ [('restart',workload['restart'])] for cmd in cmds).encode(); saved=gzip.open(hist/f'cardinality-{a.kind}-1000000.sql.gz','rb').read(); assert generated==saved,'SQL history mismatch'
 record={'kind':a.kind,'original_sql_sha256':hashlib.sha256(saved).hexdigest(),'complete_original_prefix':True,'diagnostic_strace':a.trace,'binary_sha256':b.sha256_file(a.binary),'commands':[],'stages':{}}
 class DiagnosticDatabase(ad.ContainerDatabase):
  def _snapshot(self):
   sample=super()._snapshot()
   if sample is not None:
    try:sample['cpu.stat']=(self.cg/'cpu.stat').read_text().strip()
    except OSError as error:sample['cpu.stat_error']=str(error)
   return sample
 c=DiagnosticDatabase(a.binary,a.output/'data',image=a.image,socket='unix:///var/run/docker.sock',cpuset='0,1'); tracer=None
 try:
  for stage,cmds in workload['stages']:
   c.stage=stage
   if stage=='update_cache_invalidation' and a.trace:
    tracer=subprocess.Popen(['strace','-ttt','-T','-s','256','-e','trace=read,write,pread64,pwrite64,fdatasync,fsync','-p',str(c.pid),'-o',str(a.output/'update.strace')],stderr=subprocess.PIPE)
    time.sleep(.15)
    assert tracer.poll() is None,'strace failed to attach'
   t=time.perf_counter_ns()
   for cmd in cmds:
    if stage=='update_cache_invalidation': result,timing=split_query(c,cmd['sql'])
    else:result=c.query(cmd['sql']); timing=None
    record['commands'].append({'phase':stage,'command':cmd,'response':result,'timing':timing})
   record['stages'][stage]=(time.perf_counter_ns()-t)/1e9
   c.capture('after_'+stage)
   if stage=='update_cache_invalidation':break
  # Independent assertions for all issued history responses, outside their timing.
  for e in record['commands']:
   cmd,r=e['command'],e['response']; assert r.get('ok') is True
   if 'affected' in cmd:assert r['affected']==cmd['affected'],e
   if 'expected_rows' in cmd:
    expected=cmd['expected_rows']; actual=r['rows']; assert len(actual)==len(expected),e
    for row,ref in zip(actual,expected):
     assert len(row)==len(ref)
     for x,y in zip(row,ref):assert abs(x-y)<=1e-10 if isinstance(y,float) else x==y
  record['passed']=True
 except BaseException as e:record.update(passed=False,error=repr(e));raise
 finally:
  if tracer is not None:
   tracer.terminate(); tracer.communicate(timeout=5)
  c.close();record['container']=c.record; (a.output/'run.json').write_text(json.dumps(record,indent=2))
if __name__=='__main__':main()
