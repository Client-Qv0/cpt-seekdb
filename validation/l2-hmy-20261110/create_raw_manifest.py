#!/usr/bin/env python3
"""Hash local full inputs and compare actual request streams for each pair."""
import gzip
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
dest = root / "raw-evidence-manifest.json"
if dest.exists():
    raise SystemExit("refusing to overwrite manifest")


def digest(path, decompress=False):
    h = hashlib.sha256()
    opener = gzip.open if decompress else open
    with opener(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


files = []
pairs = []
for name in ("paired-main", "paired-overflow", "simd-paired-main", "simd-paired-overflow"):
    directory = root / name / "results"
    for fixture in sorted(directory.glob("workload-*/workload.json.gz")):
        files.append({"path": str(fixture.relative_to(root)), "bytes": fixture.stat().st_size, "sha256": digest(fixture)})
    for rd in sorted(directory.glob("hmy-*")):
        pair = {"round": rd.name}
        for phase in ("initial", "restart"):
            hashes = {}
            for label in ("base", "candidate"):
                file = rd / label / phase / "requests.jsonl.gz"
                hashes[label] = digest(file, decompress=True)
                files.append({"path": str(file.relative_to(root)), "bytes": file.stat().st_size,
                              "sha256": digest(file), "uncompressed_sha256": hashes[label]})
            if hashes["base"] != hashes["candidate"]:
                raise SystemExit(f"request mismatch in {rd.name}/{phase}")
            pair[phase + "_request_sha256"] = hashes["base"]
        pairs.append(pair)
dest.write_text(json.dumps({"scope": "Full fixtures and input requests remain local; not all are included in Git.",
                            "files": files, "pairs": pairs}, indent=2) + "\n")
print(json.dumps({"files": len(files), "pairs": len(pairs), "all_pair_requests_identical": True}))
