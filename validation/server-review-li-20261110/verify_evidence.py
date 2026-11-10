from pathlib import Path
import json,hashlib
p=Path(__file__).parent; repo=p.parents[1]
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
m=json.loads((p/'EVIDENCE_MANIFEST.json').read_text()); errors=[]
for e in m['published']:
 f=p/e['path']
 if not f.is_file() or f.stat().st_size!=e['bytes'] or sha(f)!=e['sha256']:errors.append(e['path'])
assert not errors,errors
binding=json.loads((p/'source-binding.json').read_text())
for e in binding['files']:assert sha(repo/e['path'])==e['sha256'],e['path']
assert (p/'pipeline.exit').read_text().strip()=='0'
assert (p/'runner.exit').read_text().strip()=='0'
print('Verified',len(m['published']),'published files, source/Agent binding and successful pipeline markers')
