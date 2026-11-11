import pathlib,subprocess,json,os,statistics,fcntl,shutil
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c4-20261111')
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not subprocess.check_output(['docker','ps','-q'],env=env).strip()
shutil.copytree(T/'sql-lane-edges',R/'checks-sql-lane-edges',ignore=shutil.ignore_patterns('data'))
A='sha256:4dcb69128fbea4448e1dc4b0b37c5412ce788290a4fa410b1d976c1fc002de74'
B=json.loads((R/'runtime/candidate-image.json').read_text())[0]['Id']
bench=R/'baseline/validation/perf-20261110-stdio/scripts/bench_portable.py'
def phase(name,seeds,rows,queries):
 cmd=['/var/tmp/minivectordb-paired-venv/bin/python',str(bench),'--images','A='+A,'B='+B,'--output-root',str(R/name),'--data-root',str(T/(name+'-data')),'--docker-host',env['DOCKER_HOST'],'--prefix','c4'+name,'--seeds',*map(str,seeds),'--rows',str(rows),'--dim','128','--queries',str(queries)]
 (R/'runtime'/(name+'-command.json')).write_text(json.dumps(cmd,indent=2))
 p=subprocess.run(cmd,env=env);assert p.returncode==0,name
 entries=[json.loads(x) for x in (R/name/'runner.stdout.log').read_text().splitlines() if x.startswith('{')]
 pairs={}
 for x in entries:pairs.setdefault(x['round'],{})[x['label']]=x
 metrics={}
 for metric in entries[0]['times']:
  changes=[1-x['B']['times'][metric]/x['A']['times'][metric] for x in pairs.values()]
  metrics[metric]={'reductions':changes,'median':statistics.median(changes),'min':min(changes),'max':max(changes),'wins':sum(x>0 for x in changes)}
 summary={'name':name,'pairs':len(pairs),'baseline_image':A,'candidate_image':B,'metrics':metrics,'note':'Positive reduction is faster; first query and restart separate, no official score estimate.'}
 (R/(name+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
 print(name.upper()+'_SUMMARY '+json.dumps(summary),flush=True)
 return summary
main=phase('main',[3179,3181,3187,3179,3181,3187],10000,1000)
noise=json.loads((R/'aa1-summary.json').read_text())['max']
m=main['metrics']
passes=m['query_s']['median']>=.05 and m['query_s']['median']>noise and m['query_s']['wins']>=5
passes=passes and all(m[k]['median']>=-.05 for k in ['write_s','filtered_query_s','unfiltered_query_s']) and m['restart_ready_s']['median']>=-.10
if not passes:
 (R/'PERFORMANCE_STOP.json').write_text(json.dumps({'phase':'main','reason':'predeclared gate not met','metrics':m},indent=2));raise SystemExit(2)
holdout=phase('holdout',[66007,66029,66041],10000,1000)
m=holdout['metrics'];passes=m['query_s']['median']>=.05 and m['query_s']['wins']>=2
passes=passes and all(m[k]['median']>=-.05 for k in ['write_s','filtered_query_s','unfiltered_query_s']) and m['restart_ready_s']['median']>=-.10
if not passes:
 (R/'PERFORMANCE_STOP.json').write_text(json.dumps({'phase':'holdout','reason':'predeclared gate not met','metrics':m},indent=2));raise SystemExit(2)
overflow=phase('overflow',[3179,3181,3187],32000,100)
m=overflow['metrics'];passes=all(m[k]['median']>=-.05 for k in ['query_s','write_s','filtered_query_s','unfiltered_query_s']) and m['restart_ready_s']['median']>=-.10
if not passes:
 (R/'PERFORMANCE_STOP.json').write_text(json.dumps({'phase':'overflow','reason':'predeclared gate not met','metrics':m},indent=2));raise SystemExit(2)
print('PAIRED_GATES_PASS',flush=True)
