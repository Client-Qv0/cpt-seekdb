import json,urllib.request,base64,concurrent.futures,hashlib
from pathlib import Path
p=Path(__file__).parent/'public-package'; p.mkdir(exist_ok=True)
t=json.loads(Path('/home/li/minivectordb-v2-work/planning-20261109/official-tree.json').read_text()); entries=[e for e in t['tree'] if e['type']=='blob' and e['path'].startswith('mysqltest/')]
def fetch(e):
 q=p/e['path']; q.parent.mkdir(parents=True,exist_ok=True)
 d=json.load(urllib.request.urlopen(e['url'],timeout=30)); b=base64.b64decode(d['content']); assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==e['sha']; q.write_bytes(b); return e['path']
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 for f in ex.map(fetch,entries):print(f,flush=True)
(p/'binding.json').write_text(json.dumps({'commit':t['sha'],'files':entries},indent=2))
