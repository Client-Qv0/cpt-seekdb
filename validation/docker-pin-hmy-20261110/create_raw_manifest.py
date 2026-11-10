#!/usr/bin/env python3
"""Hash retained full inputs and verify pairwise request streams."""
import gzip
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
dest = root / "raw-evidence-manifest.json"
if dest.exists():
    raise SystemExit("refusing to overwrite evidence manifest")


def digest(path, decompress=False):
    h = hashlib.sha256()
    with (gzip.open(path, "rb") if decompress else path.open("rb")) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


files, pairs = [], []
for name in ("paired-main", "paired-overflow", "noise-overflow"):
    directory = root / name / "results"
    for fixture in sorted(directory.glob("workload-*/workload.json.gz")):
        files.append({"path": str(fixture.relative_to(root)), "bytes": fixture.stat().st_size, "sha256": digest(fixture)})
    for rd in sorted(directory.glob("hmy-*")):
        pair = {"round": rd.name}
        for phase in ("initial", "restart"):
            hashes = {}
            for label in ("base", "candidate"):
                path = rd / label / phase / "requests.jsonl.gz"
                hashes[label] = digest(path, decompress=True)
                files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                              "sha256": digest(path), "uncompressed_sha256": hashes[label]})
            if hashes["base"] != hashes["candidate"]:
                raise SystemExit(f"request mismatch: {rd.name}/{phase}")
            pair[phase + "_request_sha256"] = hashes["base"]
        pairs.append(pair)
for label in ("candidate-a", "production"):
    result = json.loads((root / f"{label}-recovery/result.json").read_text())
    for phase in ("before", "after"):
        path = root / f"{label}-recovery" / (phase + "-trace.jsonl.gz")
        actual = digest(path)
        if actual != result["trace_sha256"][phase]:
            raise SystemExit(f"recovery trace mismatch: {label}/{phase}")
        files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": actual})
dest.write_text(json.dumps({"scope": "Complete large input and recovery traces remain local; not all are committed.",
                            "files": files, "pairs": pairs}, indent=2) + "\n")
print(json.dumps({"files": len(files), "pairs": len(pairs), "all_pair_requests_identical": True,
                  "all_recovery_trace_hashes_match": True}))
