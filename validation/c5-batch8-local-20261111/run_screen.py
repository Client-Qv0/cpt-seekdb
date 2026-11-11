import pathlib,subprocess,json,os,statistics,fcntl
R=pathlib.Path(__file__).resolve().parent;T=pathlib.Path('/var/tmp/minivectordb-c5-batch8-20261111')
env=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-c3-20261111/docker.sock')
lock=open('/var/tmp/minivectordb-benchmark.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert json.loads((R/'checks-sql-batch8/report.json').read_text())['status']=='pass'
assert not subprocess.check_output(['docker','ps','-q'],env=env).strip()
A='sha256:4dcb69128fbea4448e1dc4b0b37c5412ce788290a4fa410b1d976c1fc002de74';B=json.loads((R/'runtime/image.json').read_text())[0]['Id']
def phase(name,seeds,rows,queries):
 cmd=['/var/tmp/minivectordb-paired-venv/bin/python',str(R/'benchmark-tools/bench_portable.py'),'--images','A='+A,'B='+B,'--output-root',str(R/name),'--data-root',str(T/(name+'-data')),'--docker-host',env['DOCKER_HOST'],'--prefix','c5'+name,'--seeds',*map(str,seeds),'--rows',str(rows),'--dim','128','--queries',str(queries)]
 (R/'runtime'/(name+'-command.json')).write_text(json.dumps(cmd,indent=2))
 p=subprocess.run(cmd,env=env,timeout=1800);assert p.returncode==0,name
 rows=[json.loads(x) for x in (R/name/'runner.stdout.log').read_text().splitlines() if x.startswith('{')]
 pairs={}
 for x in rows:pairs.setdefault(x['round'],{})[x['label']]=x
 metrics={}
 for metric in rows[0]['times']:
  ratios=[1-x['B']['times'][metric]/x['A']['times'][metric] for x in pairs.values()]
  metrics[metric]={'paired_reductions':ratios,'median':statistics.median(ratios),'min':min(ratios),'max':max(ratios),'wins':sum(x>0 for x in ratios)}
 summary={'phase':name,'pairs':len(pairs),'metrics':metrics,'baseline_image':A,'candidate_image':B,'scope':'short screen only; not full retention matrix or official score'}
 (R/(name+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n');print(name.upper()+' '+json.dumps(summary),flush=True)
 return metrics
main=phase('screen-main',[3179,3181,3187],10000,1000)
overflow=phase('screen-overflow',[3179],32000,100)
flags={}
flags['main_query_gain']=main['query_s']['median']>=.05 and main['query_s']['wins']>=2
for name,m in [('main',main),('overflow',overflow)]:
 for k in ['write_s','filtered_query_s','unfiltered_query_s']:
  flags[name+'_'+k]=m[k]['median']>=-.05
 flags[name+'_restart_ready_s']=m['restart_ready_s']['median']>=-.10
flags['overflow_query_s']=overflow['query_s']['median']>=-.05
(R/'SCREEN_GATES.json').write_text(json.dumps({'checks':flags,'pass':all(flags.values()),'screen_only':True,'formal_submission':False},indent=2)+'\n')
print('SCREEN_GATES '+json.dumps(flags),flush=True)
