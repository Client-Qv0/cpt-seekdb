"""Copy the exact local driver sources used in the completed runs."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path('.')
out = root / 'validation/benchmark-public-hmy-20261109/frozen-tools'
out.mkdir(parents=True, exist_ok=True)
names = ['benchmark_public_validation.py', 'audit_performance.py', 'paired_benchmark.py', 'cardinality_probe.py']
result = {}
for name in names:
    source = root / 'tests' / name
    target = out / name
    shutil.copy2(source, target)
    result[name] = hashlib.sha256(target.read_bytes()).hexdigest()
(out / 'sha256.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
