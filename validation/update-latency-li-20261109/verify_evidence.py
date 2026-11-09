from pathlib import Path
import json,hashlib
p=Path(__file__).parent; repo=p.parents[1]
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
m=json.loads((p/'evidence-manifest.json').read_text()); failures=[]
for e in m['files']:
 f=p/e['path']
 if not f.is_file() or f.stat().st_size!=e['bytes'] or sha(f)!=e['sha256']:failures.append(e['path'])
learning=m['learning_material']; assert sha(repo/learning['path'])==learning['sha256']
for e in json.loads((p/'binary-manifest.json').read_text())['files']:assert sha(repo/e['path'])==e['sha256'],e['path']
print(f"New evidence: {len(m['files'])} committed-scope files, {len(failures)} failures; learning and binary bindings verified")
assert not failures,failures
