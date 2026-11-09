"""Check the previous file's original bytes survived the append unchanged."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--prior-file', type=Path, required=True)
p.add_argument('--current-file', type=Path, default=Path('agent/conversation.json'))
args = p.parse_args()
prior, current = args.prior_file.read_bytes(), args.current_file.read_bytes()
offset = prior.rfind(b'}')
if offset < 0 or not current.startswith(prior[:offset]) or not current.endswith(prior[offset:]):
    raise SystemExit('Previous bytes are not preserved around the appended property.')
prior_sha, current_sha = hashlib.sha256(prior).hexdigest(), hashlib.sha256(current).hexdigest()
old_document, document = json.loads(prior), json.loads(current)
if set(document) - set(old_document) != {'current_session_hmy_20261109'} or any(
        document.get(key) != value for key, value in old_document.items()):
    raise SystemExit('Earlier properties changed or more than one new property appeared.')
if document['current_session_hmy_20261109']['prior_material_sha256'] != prior_sha:
    raise SystemExit('Prior material SHA does not match the appended metadata.')
print(f'prior_bytes={len(prior)} current_bytes={len(current)}')
print(f'prior_sha256={prior_sha}')
print(f'current_sha256={current_sha}')
print('previous bytes preserved; one new top-level property appended')
