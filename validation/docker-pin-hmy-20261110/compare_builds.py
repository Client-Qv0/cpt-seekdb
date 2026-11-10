#!/usr/bin/env python3
"""Compare the two no-cache builds without claiming identical image digests."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parent
out = root / "build-comparison.json"
if out.exists():
    raise SystemExit("refusing to overwrite comparison")
results = {}
for label in ("candidate-a", "candidate-b"):
    log = (root / f"{label}-build.txt").read_text()
    if not log.rstrip().endswith("exit=0") or "/etc/ssl/certs/ca-certificates.crt: OK" not in log:
        raise SystemExit(f"{label}: incomplete build or certificate check")
    packages = sorted(re.findall(r"Unpacking\s+(\S+)\s+\(([^)]+)\)", log))
    if len(packages) < 60:
        raise SystemExit(f"{label}: too few package records: {len(packages)}")
    hashes = re.findall(r"^([0-9a-f]{64})\s+", (root / f"{label}-inputs.txt").read_text(), re.M)
    binary = re.findall(r"^([0-9a-f]{64})\s+", (root / f"{label}-binary-comparison.txt").read_text(), re.M)
    if len(binary) != 2 or binary[0] != binary[1]:
        raise SystemExit(f"{label}: image and native binaries differ")
    results[label] = {"package_versions": packages, "source_hashes": hashes,
                      "binary_sha256": binary[0],
                      "image_id": json.loads((root / f"{label}-image.json").read_text())[0]["Id"]}
a, b = results["candidate-a"], results["candidate-b"]
if a["package_versions"] != b["package_versions"] or a["source_hashes"] != b["source_hashes"] or a["binary_sha256"] != b["binary_sha256"]:
    raise SystemExit("independent builds differ in versions, input hashes or binary")
summary = {"status": "PASS", "no_cache_builds": 2, "package_records": len(a["package_versions"]),
           "package_versions_identical": True, "source_hashes_identical": True,
           "binary_sha256": a["binary_sha256"],
           "image_ids": [a["image_id"], b["image_id"]],
           "identical_whole_image_not_claimed": True,
           "build_log_sha256": {label: hashlib.sha256((root / f"{label}-build.txt").read_bytes()).hexdigest() for label in results},
           "package_versions": a["package_versions"]}
out.write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "package_versions"}, indent=2))
