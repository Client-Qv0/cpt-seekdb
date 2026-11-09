"""Verify the Git index matches intended bytes and retained evidence manifests."""
import hashlib
import json
from pathlib import Path
import subprocess


def git(*args):
    return subprocess.check_output(['git', *args])


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def blob_hash(path, algorithm):
    digest = hashlib.new(algorithm)
    digest.update(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


algorithm = git('rev-parse', '--show-object-format').decode().strip()
index = {}
for entry in git('ls-files', '--stage', '-z').split(b'\0'):
    if entry:
        head, name = entry.split(b'\t', 1)
        mode, digest, stage = head.decode().split()
        if stage != '0':
            raise SystemExit('Unmerged index entry present')
        index[name.decode('utf-8')] = digest
names = [name.decode('utf-8') for name in git('diff', '--cached', '--name-only', '-z').split(b'\0') if name]
if not names or any(name.startswith('rust/') for name in names):
    raise SystemExit('Nothing staged or unrelated rust/ file staged')
total = 0
for name in names:
    path = Path(name)
    if not path.is_file() or index.get(name) != blob_hash(path, algorithm):
        raise SystemExit(f'Staged blob differs from working file: {name}')
    total += path.stat().st_size

checked = 0
for folder in ('validation/benchmark-public-hmy-20261109', 'validation/agent-learning-hmy-20261109'):
    root = Path(folder)
    manifest = json.loads((root / 'evidence-manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = root / item['path']
        if str(path) not in index or not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
            raise SystemExit(f'Missing or changed indexed evidence: {path}')
        checked += 1
    for name, expected in manifest['source_sha256'].items():
        path = Path(name)
        if folder.endswith('benchmark-public-hmy-20261109') and name == 'agent/conversation.json':
            current = json.loads(path.read_text(encoding='utf-8'))
            if current['current_session_hmy_20261109']['prior_material_sha256'] != expected:
                raise SystemExit('Learning material prior hash mismatch')
        elif str(path) not in index or sha256(path) != expected:
            raise SystemExit(f'Source hash mismatch: {path}')
for path in ('src/engine.cpp', 'Dockerfile', 'agent/conversation.json'):
    if path not in index:
        raise SystemExit(f'Required submission input absent from index: {path}')
print(json.dumps({'staged_files': len(names), 'staged_worktree_bytes': total,
                  'manifest_evidence_files': checked, 'index_blob_hashes_match': True,
                  'required_submission_inputs_present': True, 'rust_staged': False}, indent=2))
