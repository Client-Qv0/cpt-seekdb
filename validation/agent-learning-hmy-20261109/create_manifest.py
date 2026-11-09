"""Hash this round's evidence without changing any older manifest."""
import hashlib
import json
from pathlib import Path

root = Path('validation/agent-learning-hmy-20261109')
target = root / 'evidence-manifest.json'
if target.exists():
    raise SystemExit('Manifest already exists; refusing to overwrite.')
def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()
files = [{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
         for p in sorted(root.rglob('*')) if p.is_file() and p != target]
source = {str(p): sha(p) for p in (Path('agent/conversation.json'), Path('tests/test_agent_material.py'))}
target.write_text(json.dumps({'files': files, 'source_sha256': source}, indent=2) + '\n')
for item in files:
    p = root / item['path']
    if p.stat().st_size != item['bytes'] or sha(p) != item['sha256']:
        raise SystemExit(f'Mismatch after manifest creation: {p}')
print(f'new evidence files={len(files)} verified; source hashes={len(source)}')
