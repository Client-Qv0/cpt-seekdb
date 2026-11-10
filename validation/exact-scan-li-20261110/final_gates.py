from pathlib import Path
import json,hashlib,statistics,subprocess
p=Path(__file__).parent;repo=p.parents[1];c=json.loads((p/'COMPARISONS.json').read_text());m=json.loads((p/'MILLION_GATE.json').read_text());r=json.loads((p/'resource-final/docker-resource-regression-results.json').read_text())
q=lambda n,k:c[n]['metrics'][k]['median_reduction_percent']
checks={'main_query_15':q('final-b-main','query_s')>=15,'main_wins_5':c['final-b-main']['metrics']['query_s']['wins']>=5,'filtered_guard':q('final-b-main','filtered_query_s')>=-5,'unfiltered_guard':q('final-b-main','unfiltered_query_s')>=-5,'write_guard':q('final-b-main','write_s')>=-5,'restart_guard':q('final-b-main','restart_ready_s')>=-10,'overflow_query_guard':q('final-b-overflow','query_s')>=-5,'overflow_write_guard':q('final-b-overflow','write_s')>=-5,'overflow_restart_guard':q('final-b-overflow','restart_ready_s')>=-10,'holdout_10':q('final-b-holdout','query_s')>=10,'holdout_wins_2':c['final-b-holdout']['metrics']['query_s']['wins']>=2,'simd_increment_5':q('c2-c1-main','query_s')>=5,'million_memory':m['passed'],'resource_tests':r['success'] and r['tests_run']==4 and r['skipped']==0,'resource_no_oom':all(not x['docker_final_state']['OOMKilled'] for x in r['containers'])}
for name in ['official','recovery']:
 f=p/('c2-official-all/result.json' if name=='official' else 'c2-recovery/result.json');d=json.loads(f.read_text());checks[name]=d.get('passed',d.get('status')=='PASS')
rows=sorted((p/'aa-1/results').glob('li-exact-aa1-*'));diff=[abs(1-json.loads((x/'a2/result.json').read_text())['times']['query_s']/json.loads((x/'a1/result.json').read_text())['times']['query_s']) for x in rows];checks['AA']=len(diff)==6 and statistics.median(diff)<=.03 and max(diff)<=.10
b=(repo/'agent/conversation.json').read_bytes();checks['material_size']=len(b)<131072
checks['binary']=hashlib.sha256((repo/'build-exact-c2/minivectordb').read_bytes()).hexdigest()=='b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67'
assert all(checks.values()),checks
subprocess.run(['python3',str(repo/'tests/test_agent_material.py'),'-v'],stdout=(p/'agent-material-final.log').open('w'),stderr=subprocess.STDOUT,check=True)
(p/'FINAL_GATES.json').write_text(json.dumps({'checks':checks,'passed':True,'selected':'C2','agent_bytes':len(b),'agent_sha256':hashlib.sha256(b).hexdigest(),'note':'Acceptance against9cea; no officialscore prediction; cold firstquery regression disclosed separately.'},indent=2)+'\n');print('ALL',len(checks),'GATES PASS; materialbytes',len(b))
