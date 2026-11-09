"""Retain the measured 2468 driver before its later Docker-volume cleanup edit."""
import hashlib
import json
from pathlib import Path

root = Path('validation/benchmark-public-hmy-20261109')
metadata = json.loads((root / 'seed-2468-audit/metadata.json').read_text())
expected = next(value for name, value in metadata['tool_sha256'].items() if name.endswith('/benchmark_public_validation.py'))
current = Path('tests/benchmark_public_validation.py').read_text()
new = '''        # `docker create` can allocate an anonymous volume declared by the image.
        # Remove only volumes created for this temporary, task-owned container.
        subprocess.run(['docker', 'rm', '-v', name], stdout=subprocess.DEVNULL, check=True)'''
old = "        subprocess.run(['docker', 'rm', name], stdout=subprocess.DEVNULL, check=True)"
assert current.count(new) == 1
original = current.replace(new, old).encode('utf-8')
actual = hashlib.sha256(original).hexdigest()
assert actual == expected, (actual, expected)
(root / 'driver-2468-as-measured.py').write_bytes(original)
print(f'reconstructed driver SHA-256 matches run metadata: {actual}')
