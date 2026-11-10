#!/usr/bin/env python3
"""Diagnostic baseline sampling, never performance acceptance evidence."""
import gzip,json,pathlib,subprocess,time
root=pathlib.Path(__file__).resolve().parent
fixture=root/'aa-1/results/workload-3179-10000-128-1000/workload.json.gz'
with gzip.open(fixture,'rt') as f:w=json.load(f)
out=root/'profile-baseline-retry';out.mkdir()
err=(out/'stderr.log').open('w')
command=['perf','record','-F','199','-e','cpu-clock:u','--call-graph','dwarf','-o',str(out/'perf.data'),'--','/home/li/minivectordb-review-20261110/build-server-review/minivectordb','--data-dir',str(out/'data')]
p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,bufsize=1)
assert json.loads(p.stdout.readline())['type']=='ready'
records=[]
def req(sql=None,op='execute'):
    start=time.perf_counter();p.stdin.write(json.dumps({'id':len(records)+1,'op':op,**({'sql':sql,'search_mode':'exact'} if sql else {})})+'\n');p.stdin.flush();r=json.loads(p.stdout.readline());dt=time.perf_counter()-start;assert r.get('ok'),r;return dt
req(w['create'])
for sql in w['batches']:req(sql)
first=req(w['queries'][0]);records.append({'stage':'first_query_cache_build','elapsed_s':first})
for cycle in range(5):
    for sql in w['queries']:req(sql)
req(op='shutdown');p.stdin.close();code=p.wait();err.close();assert code==0
(out/'diagnostic.json').write_text(json.dumps({'command':command,'stages':records,'queries':5000,'scope':'native diagnostic sampling, no Docker, not final comparison; first-query wall time includes row scan and cache build','exit_code':code},indent=2)+'\n')
with (out/'perf-report.txt').open('w') as f:subprocess.run(['perf','report','--stdio','--no-children','--sort','symbol','-i',str(out/'perf.data')],stdout=f,check=True)
print(json.dumps({'exit_code':code,'first_query_s':first,'output':str(out)}))
