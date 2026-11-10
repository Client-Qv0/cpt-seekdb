import argparse,hashlib,json,pathlib,statistics
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('prefix');a=p.parse_args()
trials=[]
for rounddir in sorted((ROOT/'results').glob(a.prefix+'-*')):
    for f in sorted(rounddir.glob('*/result.json')):
        r=json.loads(f.read_text());r['round']=rounddir.name
        snaps=json.loads((f.parent/'initial/resources.json').read_text())
        r['memory_peak_bytes']=max(int(s['files']['memory.peak']) for s in snaps)
        def fields(s,name):return dict(line.split(None,1) for line in s['files'][name].splitlines())
        r['anon_max_sampled']=max(int(fields(s,'memory.stat')['anon']) for s in snaps)
        r['file_max_sampled']=max(int(fields(s,'memory.stat')['file']) for s in snaps)
        r['memory_events_final_sample']=fields(snaps[-1],'memory.events')
        r['io_stat_initial_raw']=snaps[0]['files']['io.stat'];r['io_stat_final_raw']=snaps[-1]['files']['io.stat']
        r.pop('query_times');r.pop('write_times');trials.append(r)
labels={}
for label in sorted({r['label'] for r in trials}):
    values=[r for r in trials if r['label']==label]
    metrics={**{k:[r['times'][k] for r in values] for k in values[0]['times']},**{k:[r[k] for r in values] for k in ['memory_peak_bytes','anon_max_sampled','file_max_sampled']}}
    labels[label]={k:{'median':statistics.median(v),'min':min(v),'max':max(v),'all':v} for k,v in metrics.items()}
ratios={}
for label in labels:
    if label=='baseline':continue
    pairs=[]
    for v in [r for r in trials if r['label']==label]:
        bases=[r for r in trials if r['label']=='baseline' and r['round']==v['round']]
        if bases:pairs.append({'round':v['round'],**{k:bases[0]['times'][k]/v['times'][k] for k in v['times']}})
    ratios[label]={'pairs':pairs,'median_speedup':{k:statistics.median(x[k] for x in pairs) for k in trials[0]['times']} if pairs else {}}
out={'scope':'local controlled JSONL Docker comparison, not official score','prefix':a.prefix,'labels':labels,'ratios':ratios,'trials':trials,'oracle_checks':sum(r['oracle_checks'] for r in trials),'all_recall_one':all(r['recall']==1 for r in trials)}
dest=ROOT/'results'/(a.prefix+'-summary.json');dest.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'labels':{k:{x:{z:y for z,y in v[x].items() if z!='all'} for x in ['write_s','query_s','first_query_s','restart_ready_s','memory_peak_bytes']} for k,v in labels.items()},'speedups':{k:v['median_speedup'] for k,v in ratios.items()},'oracle_checks':out['oracle_checks']},indent=2))
