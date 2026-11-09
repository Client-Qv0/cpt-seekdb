import json, pathlib, hashlib, datetime
P=pathlib.Path(__file__).resolve().parent
ROOT=P.parent.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda n:json.loads((P/n).read_text())
reports={n:load(n) for n in ['candidate-v2-boundary-results.json','transaction-baseline-repeat-for-v2-results.json','transaction-candidate-v2-results.json','arena-retention-candidate-v2-results.json','recovery-diagnostic-candidate-v2-results.json']}

def kv(text):
    return {a:int(b) for a,b in (line.split() for line in text.splitlines())}
def values(record):
    return [v for v in ([s.get('values') for s in record.get('snapshots',[])]+record.get('samples',[])+[record.get('last_live_snapshot')]) if v]
def compact_container(r):
    vv=values(r)
    maxima={key:max((int(v.get(key,'0')) for v in vv),default=0) for key in ['memory.peak','memory.current']}
    maxima.update({key:max((kv(v.get('memory.stat','')).get(key,0) for v in vv),default=0) for key in ['anon','file']})
    events={k:max((kv(v.get('memory.events','')).get(k,0) for v in vv),default=0) for k in ['max','oom','oom_kill']}
    actual=sorted(set((v.get('memory.max'),v.get('memory.swap.max'),v.get('cpu.max'),v.get('cpuset.cpus.effective')) for v in vv))
    assert all(a[:3]==('134217728','0','200000 100000') for a in actual),actual
    assert r['docker_final_state']['OOMKilled'] is False,r['name']
    assert events['oom']==events['oom_kill']==0,events
    return {'name':r['name'],'label':r['label'],'binary_sha256':r['binary_sha256'],'image_id':r['image_id'],'actual_limits_tuples':actual,'observed_maxima_bytes':maxima,'observed_events_max':events,'docker_final_state':r['docker_final_state'],'requested_kill':r['requested_kill'],'sample_error_count':len(r.get('sample_errors',[])),'last_live_io_stat_raw':r.get('last_live_snapshot',{}).get('io.stat'),'data_device':r.get('data_device')}

summary={'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'production_tree_sha256':'df56a37dcbae572b6283dfd4ee67cccc1e7e15f2117b59760cf7628936ae18f3','candidate_binary_sha256':'78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c','baseline_binary_sha256':'747092fd68833b52ec80020e050d4586d443220f513d6b3d932ab3e25eea072f','source_and_binary_rechecked':False,'official_benchmark':False,'scope':'Local diagnostic evidence for exact frozen candidate V2. Real containers mount the exact selected production binary or separately identified diagnostic helper into the previously frozen runtime image; no candidate Docker image rebuild is claimed.','reports':{},'boundary':[],'transactions':[],'retention':[],'recovery':reports['recovery-diagnostic-candidate-v2-results.json']['summary'],'limitations':['Boundary uses CPU quota only; recovery helper fixes cpuset 0,1.','Transient memory.stat anon/file can lag /proc RssAnon/RssFile. Stage points are observations, not allocation census; retained continuous samples and RSS corroborate large steady-state conclusions.','memory.peak reaching memory.max with max events and page-cache reclaim is not an OOM or a leak.','Raw io.stat on shared backing device is uncalibrated; no physical IO attribution, write amplification, or official resource score is claimed.','Successful 2m is the tested ceiling, not proof of the maximum supported cardinality. Baseline first tested failure was 2m; exact threshold was not searched.','Single-run boundary/transaction/retention wall times are diagnostics, not paired performance estimates.','Independent recovery helper compiles only frozen storage implementation with -O3 -DNDEBUG. Its constructor clock is not production process end-to-end performance.','Recovery fixture copies and hash verification prepopulate the host file cache; these are process-cold, not OS-cold tests.','Recovery constructor row verification counts all rows/lengths and checks independent expected bytes at sampled keys; noncryptographic cross-version FNV is corroboration rather than an independent complete oracle.']}

for filename,d in reports.items():
    cases=d.get('cases',d.get('runs',[]))
    assert all(c['passed'] for c in cases),filename
    cc=[]
    for c in cases:
        for r in c.get('containers',[c['container']] if 'container' in c else []):cc.append(compact_container(r))
    assert d['daemon_cleanup']['stopped'],filename
    summary['reports'][filename]={'sha256':sha(P/filename),'cases_passed':len(cases),'cases_total':len(cases),'containers':cc,'daemon_cleanup':d['daemon_cleanup']}

for c in reports['candidate-v2-boundary-results.json']['cases']:
    summary['boundary'].append({'kind':c['kind'],'rows':c['rows'],'passed':c['passed'],'phases':[{'name':x['name'],'seconds':x['elapsed_seconds'],'after':x.get('after')} for x in c['phases']]})
for filename in ['transaction-baseline-repeat-for-v2-results.json','transaction-candidate-v2-results.json']:
    for c in reports[filename]['cases']:
        for x in c['phases']:
            if x['name'].endswith('_update_rollback'):
                summary['transactions'].append({'report':filename,'kind':c['kind'],'rows':c['rows'],'pending_rows':x['detail']['pending_rows'],'before':x['before'],'pending_memory':x['detail']['pending_memory'],'rollback_memory':x['after'],'elapsed_seconds':x['elapsed_seconds']})
for c in reports['arena-retention-candidate-v2-results.json']['cases']:
    summary['retention'].append({'version':c['version'],'phases':[{'name':x['name'],'seconds':x['seconds'],'settled_samples':x['settled_samples'],'settling_seconds_excluded':x['settling_seconds_excluded_from_stage_time']} for x in c['phases']]})

m=load('candidate-v2-production-manifest.json')
for f in m['files']:
    assert sha(ROOT/'build-cardinality/candidate-v2/source'/f['path'])==f['sha256'],f['path']
assert sha(ROOT/'build-cardinality/candidate-v2/release/minivectordb')==summary['candidate_binary_sha256']
assert sha(ROOT/'build-cardinality/baseline/release/minivectordb')==summary['baseline_binary_sha256']
summary['source_and_binary_rechecked']=True
out=P/'candidate-v2-diagnostic-summary.json'
assert not out.exists()
out.write_text(json.dumps(summary,indent=2)+'\n')
files=['baseline-driver.py','probe-v2.py','planned-candidate-v2-commands.json','candidate-v2-production-manifest.json','checkpoint-helper.cpp','checkpoint-helper-candidate-v2','checkpoint-helper-candidate-v2-manifest.json','recovery-timing-helper.cpp','recovery-helper-baseline','recovery-helper-candidate-v2','recovery-helper-build-candidate-v2-manifest.json','recovery-helper-candidate-v2-build.txt','arena-retention-candidate-v2.py','recovery-diagnostic-candidate-v2.py','candidate-v2-diagnostic-summary.json','candidate-v2-diagnostic-summarize.py']
for label in ['candidate-v2-boundary','transaction-baseline-repeat-for-v2','transaction-candidate-v2','arena-retention-candidate-v2','recovery-diagnostic-candidate-v2']:
    files.extend([label+'-results.json',label+'-log.txt'])
manifest={'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Candidate V2 resource/recovery diagnostics only; historical baseline and V1 evidence remain unchanged.','source_tree_sha256':summary['production_tree_sha256'],'binary_sha256':summary['candidate_binary_sha256'],'files':[{'path':n,'bytes':(P/n).stat().st_size,'sha256':sha(P/n)} for n in sorted(files)],'source_manifest_sha256':sha(P/'candidate-v2-production-manifest.json')}
mp=P/'candidate-v2-diagnostic-evidence-manifest.json'
assert not mp.exists()
mp.write_text(json.dumps(manifest,indent=2)+'\n')
print('MANIFEST_SHA256',sha(mp))
for name,rr in summary['reports'].items():print(name,rr['cases_passed'],'cases',len(rr['containers']),'containers','oom',sum(r['docker_final_state']['OOMKilled'] for r in rr['containers']),'max_events',max(r['observed_events_max']['max'] for r in rr['containers']))
for r in summary['retention']:
 print('RETENTION',r['version'],[(x['name'],x['settled_samples'][-1].get('anon'),x['settled_samples'][-1].get('file')) for x in r['phases']])
for r in summary['transactions']:print('TRANSACTION',r['report'],r['kind'],r['pending_rows'],r['pending_memory']['anon'],r['rollback_memory']['anon'])
for r in summary['boundary']:
 if r['rows']>=1000000:print('BOUNDARY',r['kind'],r['rows'],[(x['name'],x['after'].get('anon'),x['after'].get('file')) for x in r['phases'] if x['name'] in ['write','scan_first','restart_recovery']])
