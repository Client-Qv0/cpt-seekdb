from pathlib import Path
import hashlib,json,statistics,subprocess
p=Path(__file__).parent;r=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
for f in ['native.exit','sanitize.exit']:assert (p/f).read_text().strip()=='0'
for folder,rounds in [('benchmark-3179',3),('correctness-9143',1)]:
 s=json.loads((p/folder/'summary.json').read_text());c=json.loads((p/folder/'completion.json').read_text());assert s['all_passed'] and len(s['runs'])==rounds and c['tools_unchanged']
 assert all(x['readback_rows']==10000 and x['correctness']['checked_result_sets']==1011 for x in s['runs'])
for f in ['public-native.json','public-docker.json']:assert json.loads((p/f).read_text())['passed']
m=json.loads((p/'production-manifest.json').read_text());assert all(sha(r/e['path'])==e['sha256'] for e in m['files'])
assert sha(r/'build-image/minivectordb')==sha(r/'build-takeover/minivectordb')=='ffe90b07f75fbb8b38ddf225b5e04176318d3f46614e5a195c646b18314aae4d'
subprocess.run(['git','diff','--exit-code','d85b5061d2e6aa12fd0d7bcedf7b493a695c40c0','--','src','CMakeLists.txt','Dockerfile'],cwd=r,check=True)
s=json.loads((p/'benchmark-3179/summary.json').read_text());(p/'RESULTS.json').write_text(json.dumps({'upstream':'d85b5061d2e6aa12fd0d7bcedf7b493a695c40c0','median_write_seconds':statistics.median(x['timings']['write_batches_seconds'] for x in s['runs']),'median_query_seconds':statistics.median(x['timings']['warm_queries_seconds'] for x in s['runs']),'performance_rounds':3,'correctness_rounds_additional':1,'all_passed':True,'production_changed_in_takeover':False,'official_assessment':False},indent=2)+'\n')
files=[];retained=[]
for f in sorted(p.rglob('*')):
 if not f.is_file():continue
 q=f.relative_to(p)
 if '__pycache__' in q.parts or 'data' in q.parts or q.name=='evidence-manifest.json':continue
 e={'path':str(q),'bytes':f.stat().st_size,'sha256':sha(f)}
 (retained if q.name=='image-binary-copy' else files).append(e)
roots=[{'path':name,'sha256':sha(r/name)} for name in ['agent/conversation.json','tests/README.txt','HANDOFF_LI_AFTER_HMY_20261109.md']]
(p/'evidence-manifest.json').write_text(json.dumps({'files':files,'local_binary_copies':retained,'root_bindings':roots,'source_manifest':'production-manifest.json','manifest_excludes_itself':True},indent=2)+'\n');print('Verified',len(files),'evidence files,',len(m['files']),'production inputs, all local runs complete')
