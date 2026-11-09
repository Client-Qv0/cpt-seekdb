from pathlib import Path
import hashlib,json,subprocess
p=Path(__file__).parent;r=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
for name in ['paired-initial','paired-blocked']:
 d=json.loads((p/name/'summary.json').read_text());assert d['all_planned_runs_passed'] and d['identities_unchanged']
for seed in [9143,27183]:assert json.loads((p/f'oracle-seed-{seed}.json').read_text())['passed']
for name in ['public-baseline','public-docker','public-prototype','public-final-default']:assert json.loads((p/(name+'.json')).read_text())['passed']
for name in ['prototype-regression.exit','sanitize.exit']:assert (p/name).read_text().strip()=='0'
resource=json.loads((p/'resource-prototype/docker-resource-regression-results.json').read_text());assert resource['success'];assert all(not c['docker_final_state']['OOMKilled'] for c in resource['containers'])
assert all(x['passed'] for x in json.loads((p/'million-memory.json').read_text()))
for manifest,source in [('candidate-initial-manifest.json','prototype-initial-source'),('candidate-manifest.json','prototype-blocked-source')]:
 for e in json.loads((p/manifest).read_text())['files']:assert sha(p/source/e['path'])==e['sha256'],e['path']
subprocess.run(['git','diff','--exit-code','75ecbf3e60a68de7d833aa899bc0fcb4c48df47e','--','src','CMakeLists.txt','Dockerfile'],cwd=r,check=True)
json.loads((r/'agent/conversation.json').read_text());assert (r/'agent/conversation.json').stat().st_size<=131072
records=[]
for f in sorted(p.rglob('*')):
 if not f.is_file():continue
 q=f.relative_to(p)
 if 'data' in q.parts or 'memory-data' in q.parts or '__pycache__' in q.parts or f.name=='evidence-manifest.json':continue
 records.append({'path':str(q),'bytes':f.stat().st_size,'sha256':sha(f)})
binaries=[]
for f in ['build-query/minivectordb','build-query-sanitize/minivectordb','build-profile/minivectordb','build-docker/minivectordb']:
 binaries.append({'path':f,'sha256':sha(r/f)})
(p/'evidence-manifest.json').write_text(json.dumps({'files':records,'binaries':binaries,'production_changed':False,'learning_sha256':sha(r/'agent/conversation.json'),'official_assessment':False},indent=2)+'\n')
print('Verified final evidence files',len(records),'frozen prototype source manifests, tests and default production unchanged')
