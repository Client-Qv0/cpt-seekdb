from pathlib import Path
import hashlib
import json

for folder in ("update-latency-li-20261109", "exact-query-li-20261109"):
    root = Path("validation") / folder
    manifest = json.loads((root / "evidence-manifest.json").read_text())
    failures = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            failures.append(f"missing: {path}")
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            failures.append(f"mismatch: {path}")
    print(folder, len(manifest["files"]), "files;", len(failures), "failures")
    assert not failures, failures

latest = json.loads(Path("validation/exact-query-li-20261109/evidence-manifest.json").read_text())
assert hashlib.sha256(Path("agent/conversation.json").read_bytes()).hexdigest() == latest["learning_sha256"]
print("learning material hash matches")
