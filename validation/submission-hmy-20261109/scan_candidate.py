"""Scan task files for a narrow set of common credential formats before upload.

This is not a comprehensive secret scan. It prints only file paths and pattern
names, never matched text. It also inspects gzip contents used as evidence.
"""
import gzip
import json
from pathlib import Path
import re

files = [Path(p) for p in (
    'agent/conversation.json', 'tests/README.txt', 'tests/cardinality_probe.py',
    'tests/optimization_acceptance.py', 'tests/benchmark_public_validation.py',
    'tests/test_agent_material.py', 'tests/test_benchmark_public_validation.py',
)]
for directory in ('validation/agent-learning-hmy-20261109',
                  'validation/benchmark-public-hmy-20261109',
                  'validation/local-hmy-20261109',
                  'validation/worktree-migration-hmy-20261109'):
    files.extend(path for path in Path(directory).rglob('*') if path.is_file())
patterns = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github_token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'openai_key': re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{20,}'),
    'aws_access_key': re.compile(rb'AKIA[0-9A-Z]{16}'),
}
matches, gzip_files = [], 0
for path in files:
    raw = path.read_bytes()
    candidates = [('raw', raw)]
    if raw.startswith(b'\x1f\x8b'):
        candidates.append(('gzip', gzip.decompress(raw)))
        gzip_files += 1
    for representation, data in candidates:
        for name, pattern in patterns.items():
            if pattern.search(data):
                matches.append({'path': str(path), 'representation': representation, 'pattern': name})
result = {'scope': 'narrow pattern scan; not a complete sensitive-data audit',
          'files_scanned': len(files), 'gzip_contents_scanned': gzip_files, 'matches': matches}
print(json.dumps(result, ensure_ascii=False, indent=2))
if matches:
    raise SystemExit(1)
