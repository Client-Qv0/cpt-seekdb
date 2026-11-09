"""Check new evidence without changing old manifests or experiment outputs."""
import hashlib
import json
from pathlib import Path

run = Path('validation/local-hmy-20261109')
live = Path('/dev/shm/mvdb-hmy-paired-20261109')
copy = run / 'paired-output'
count = 0
for source in live.rglob('*'):
    relative = source.relative_to(live)
    if 'data' in relative.parts or not source.is_file():
        continue
    a, b = source.read_bytes(), (copy / relative).read_bytes()
    assert hashlib.sha256(a).digest() == hashlib.sha256(b).digest(), str(relative)
    count += 1
summary = json.loads((copy / 'summary.json').read_text())
assert summary['all_planned_runs_passed'] and summary['identities_unchanged']
pairs = summary['workloads']['vector128']['pairs']
assert len(pairs) == 3 and all(pair['passed'] for pair in pairs)
learning = Path('agent/conversation.json').read_bytes()
json.loads(learning)
assert len(learning) <= 128 * 1024
print(f'evidence copies: {count} match')
print(f'paired comparisons: {len(pairs)}; all passed oracle; identities unchanged')
print(f'learning JSON: {len(learning)} bytes; valid')
