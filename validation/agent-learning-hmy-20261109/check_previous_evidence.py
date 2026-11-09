"""Verify old evidence; the intentionally changed learning file gets a new SHA."""
import hashlib
import json
from pathlib import Path

root = Path('validation/benchmark-public-hmy-20261109')
manifest = json.loads((root / 'evidence-manifest.json').read_text(encoding='utf-8'))
def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()

failures = []
for entry in manifest['files']:
    path = root / entry['path']
    if not path.is_file() or path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
        failures.append(entry['path'])
material = json.loads(Path('agent/conversation.json').read_text(encoding='utf-8'))
old_material_sha = manifest['source_sha256']['agent/conversation.json']
if material['current_session_hmy_20261109']['prior_material_sha256'] != old_material_sha:
    failures.append('learning material prior SHA is inconsistent with previous manifest')
for name, expected in manifest['source_sha256'].items():
    if name != 'agent/conversation.json' and sha(Path(name)) != expected:
        failures.append(name)
print(f'historical evidence files={len(manifest["files"])} failures={len(failures)}')
print(f'previous learning sha256={old_material_sha}')
print(f'current learning sha256={sha(Path("agent/conversation.json"))}')
print('learning material deliberately changed in this round; old manifest was not rewritten')
if failures:
    raise SystemExit('\n'.join(failures))
