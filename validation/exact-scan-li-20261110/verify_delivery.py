from pathlib import Path
import json,hashlib
p=Path(__file__).parent;repo=p.parents[1]
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
m=json.loads((p/'EVIDENCE_MANIFEST.json').read_text());bad=[]
for e in m['published']:
 f=p/e['path']
 if not f.is_file() or f.stat().st_size!=e['bytes'] or sha(f)!=e['sha256']:bad.append(e['path'])
assert not bad,bad
b=json.loads((p/'FINAL_BINDING.json').read_text())
for e in b['production_inputs']:assert sha(repo/e['path'])==e['sha256'],e['path']
assert sha(repo/'agent/conversation.json')==b['agent_sha256'] and sha(repo/'TEAM_HANDOFF.md')==b['handoff_sha256']
assert sha(repo/'build-exact-c2/minivectordb')=='b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67'
g=json.loads((p/'FINAL_GATES.json').read_text());assert g['passed'] and all(g['checks'].values())
print('Delivery verified:',len(m['published']),'published files, all20gates, source/material/handoff/binary bindings')
