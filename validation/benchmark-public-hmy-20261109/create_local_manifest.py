"""Create a new manifest only for this round; never alter historical manifests."""
import hashlib
import json
from pathlib import Path

root = Path('validation/benchmark-public-hmy-20261109')
manifest_path = root / 'evidence-manifest.json'
if manifest_path.exists():
    raise SystemExit('manifest exists; refusing to overwrite')
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()
files = []
for path in sorted(root.rglob('*')):
    if path.is_file() and path != manifest_path:
        files.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
sources = [Path('tests/benchmark_public_validation.py'), Path('tests/test_benchmark_public_validation.py'),
           Path('tests/cardinality_probe.py'), Path('tests/optimization_acceptance.py'),
           Path('tests/README.txt'), Path('agent/conversation.json')]
source_hashes = {str(path): digest(path) for path in sources}
manifest_path.write_text(json.dumps({'files': files, 'source_sha256': source_hashes}, indent=2) + '\n')
for entry in files:
    path = root / entry['path']
    assert path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256'], entry['path']
print(f'{len(files)} evidence files verified; {len(source_hashes)} source/material hashes recorded')
