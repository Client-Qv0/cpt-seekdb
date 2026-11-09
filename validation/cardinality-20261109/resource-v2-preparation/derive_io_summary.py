from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1])
entries=[]
for path in sorted(root.glob('*-pair-*/run.json')):
 run=json.loads(path.read_text())
 main=run.get('container_record',{})
 restart=run.get('restart_container_record',run.get('recovery',{}).get('container_record',{}))
 for role,record in (('main',main),('restart',restart)):
  sample=record.get('last_live_snapshot',{})
  raw=sample.get('io.stat')
  devices=[]
  for line in (raw or '').splitlines():
   fields=line.split()
   values={'device_major_minor':fields[0]}
   for field in fields[1:]:
    key,value=field.split('=',1)
    values[key]=int(value)
   devices.append(values)
  entries.append({'run':run['run_label'],'variant':run['variant'],'pair_index':run['pair_index'],'role':role,'run_json_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'cgroup_path':record.get('cgroup_path'),'data_device':record.get('data_device'),'last_live_monotonic':sample.get('monotonic'),'last_live_stage':sample.get('stage'),'raw_io_stat':raw,'device_counters':devices})
report={'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_root':str(root),'entry_count':len(entries),'interpretation':'These are each database cgroup last-live io.stat raw cumulative device counters, not database file sizes, not finalized lifetime writeback accounting, and not official physical IO. No sync or dedicated-device attribution calibration is performed. Devices are retained separately without summing possibly stacked-device counters. Missing/empty counters are preserved rather than fabricated.','entries':entries}
(root/'io-last-live-summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'entry_count':len(entries),'output':str(root/'io-last-live-summary.json'),'script_sha256':report['script_sha256']},indent=2))
