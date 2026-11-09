"""Prepare a local, parameterized copy of the historical paired harness."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path('/mnt/e/MiniVectorDB/work')
out = root / 'validation/local-hmy-20261109'
candidate = Path('/mnt/e/MiniVectorDB/candidate-source')
for name in ('.dockerignore', 'Dockerfile'):
    shutil.copy2(root / name, candidate / name)
baseline_manifest = json.loads((root / 'validation/cardinality-20261109/candidate-v2-production-manifest.json').read_text())
items = []
for entry in baseline_manifest['files']:
    p = candidate / entry['path']
    data = p.read_bytes()
    items.append({'path': entry['path'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
(out / 'candidate-manifest.json').write_text(json.dumps({'files': items}, indent=2) + '\n')
binary = Path('/mnt/e/MiniVectorDB/build-release/minivectordb')
(out / 'control-lock.json').write_text(json.dumps({'baseline_binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}) + '\n')
script = (root / 'tests/paired_benchmark.py').read_text()
old = 'if filesystem != "ext4":'
assert script.count(old) == 1
script = script.replace(old, 'if filesystem not in ("ext4", "tmpfs"):')
(out / 'paired_tmpfs.py').write_text(script)
print('Prepared candidate manifest, local control lock and tmpfs-compatible harness.')
