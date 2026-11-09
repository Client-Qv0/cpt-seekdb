from pathlib import Path
import json,hashlib
p=Path(__file__).parent;r=p/'prototype-blocked-source';old=Path('/opt/minivectordb-v2/validation/cardinality-20261109/candidate-v2-production-manifest.json');m=json.loads(old.read_text());files=[]
for name in [e['path'] for e in m['files']]+['src/exact_distance.hpp']:
 b=(r/name).read_bytes();files.append({'path':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
tree=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest();(p/'candidate-manifest.json').write_text(json.dumps({'files':files,'tree_sha256':tree},indent=2));(p/'control-lock.json').write_text(json.dumps({'baseline_binary_sha256':'78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c'}))
