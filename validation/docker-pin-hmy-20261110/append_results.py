#!/usr/bin/env python3
"""Add actual build and correctness results; do not infer student contributions."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
out = Path(__file__).resolve().parent
material = root / "agent/conversation.json"
manifest = out / "agent-results-manifest.json"
before = "ace90e6379d544f11e77942cdadedc880a811a0bd10ffe53ff01736f47df2283"
key = "docker_pinning_followup_20261110"
if manifest.exists():
    raise SystemExit("refusing to overwrite manifest")
raw = material.read_bytes()
if hashlib.sha256(raw).hexdigest() != before:
    raise SystemExit("material changed; preserve and reassess before appending")
old = json.loads(raw)
if key in old:
    raise SystemExit("results already present")
builds = json.loads((out / "build-comparison.json").read_text())
recovery = json.loads((out / "production-recovery/result.json").read_text())
official = json.loads((out / "production-official-all/result.json").read_text())
if builds["status"] != "PASS" or recovery["status"] != "PASS" or official["passed"] is not True:
    raise SystemExit("required evidence did not pass")
experiments = []
for name in ("paired-main", "paired-overflow", "noise-overflow"):
    path = out / name / "paired-summary.json"
    summary = json.loads(path.read_text())
    experiments.append({
        "experiment": name,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "faster_query_pairs": summary["faster_query_pairs"],
        "pair_count": len(summary["pairs"]),
        "median_paired_query_reduction": summary["median_paired_query_reduction"],
        "oracle_checks": summary["total_oracle_checks"],
        "rounds": [{"round": p["round"], "base_query_s": p["base"]["times"]["query_s"],
                    "candidate_query_s": p["candidate"]["times"]["query_s"],
                    "paired_query_reduction": p["query_reduction"]} for p in summary["pairs"]]
    })
entry = {
    "scope": "Agent actions and local tool results; not evidence of unspoken student understanding.",
    "related_real_user_request": "/user_followup_20261110/messages/0/content",
    "agent_summary": "Agent investigated locked Docker dependencies using a pinned Ubuntu base and dated package snapshot; the user did not propose or explain this implementation.",
    "tool_results": [
        {"source": "tool_output_summary", "content": "Two independent no-cache candidate builds passed; 69 unpacked package-version records and source hashes matched. Their database binaries and the prior native baseline all had SHA256 1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9. Whole image IDs differed; byte-identical images are not claimed."},
        {"source": "tool_output_summary", "content": "The actual repository Dockerfile matched the tested candidate file by SHA256 6178916e2baf4b9a3b3481c1949fbbee71edca0cdae07ace94feebed19990c32. The default production image passed the unmodified official f4d4e266 public handshake, CRUD and all 20 public cases."},
        {"source": "tool_output", "content": (out / "production-recovery.txt").read_text().strip(), "artifact_sha256": hashlib.sha256((out / "production-recovery.txt").read_bytes()).hexdigest()},
        {"source": "tool_output_summary", "content": "The actual default Docker entry under 128 MiB and zero swap was killed after 100 acknowledged batches while a later transaction was still open. A new container read back all 10,000 IDs, groups and 1,280,000 FP32 components; the uncommitted update, delete and insert were absent. SIGKILL exit 137 was not OOM; this does not test power loss."},
        {"source": "tool_output_summary", "content": "Actual benchmark results and a separately run same-image noise control are recorded below. Physical I/O only covers ready to pre-shutdown samples, not the official full lifecycle. Other containers ran on the shared host; performance conclusions remain limited."}
    ],
    "performance_experiments": experiments,
    "limitations": [
        "The user explicitly answered 不确定。 when asked to interpret the earlier L2 experiments; this is not a claimed independent technical explanation.",
        "The user reported only 本项没有有效原始分 and no more detailed platform error; the cause is unknown.",
        "No new official MySQL result, Agent score, performance score or ranking was obtained.",
        "Docker build snapshot availability and platform build-time limits remain to be verified by platform environment precheck.",
        "Full benchmark inputs and traces remain locally saved and hashed; no claim that every large input was included in the submitted Git tree."
    ]
}
prefix = raw.rstrip()
if not prefix.endswith(b"}"):
    raise SystemExit("invalid object")
new = prefix[:-1].rstrip() + (",\n  " + json.dumps(key) + ": " + json.dumps(entry, ensure_ascii=False, indent=2).replace("\n", "\n  ") + "\n}\n").encode()
if len(new) > 128 * 1024:
    raise SystemExit("material exceeds 128 KiB")
updated = json.loads(new)
if updated[key] != entry or any(updated[k] != v for k, v in old.items()):
    raise SystemExit("previous material values changed")
material.write_bytes(new)
record = {"previous_sha256": before, "sha256": hashlib.sha256(new).hexdigest(), "bytes": len(new),
          "previous_values_unchanged": True, "student_understanding_inferred": False,
          "official_score_available": False}
manifest.write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
