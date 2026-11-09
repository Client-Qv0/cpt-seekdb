#!/usr/bin/env python3
"""Read-only verification of the frozen V2 source and historical evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def check(manifest_path, base):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    for entry in manifest["files"]:
        path = base / entry["path"]
        if not path.is_file():
            failures.append(f"missing: {path.relative_to(ROOT)}")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            failures.append(f"hash mismatch: {path.relative_to(ROOT)}")
    print(f"{manifest_path.relative_to(ROOT)}: {len(manifest['files'])} files, "
          f"{len(failures)} failures")
    for failure in failures:
        print(failure)
    return not failures


def main():
    current = ROOT / "validation/cardinality-20261109"
    old = ROOT / "validation/audit-20261109-42affed2e283"
    outcomes = [
        check(current / "candidate-v2-production-manifest.json", ROOT),
        check(old / "evidence-manifest.json", old),
        check(current / "evidence-manifest.json", current),
    ]
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
