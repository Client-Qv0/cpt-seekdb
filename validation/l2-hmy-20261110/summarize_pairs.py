#!/usr/bin/env python3
"""Summarize completed pairs, preserving individual rounds and actual cgroup values."""
import json
from pathlib import Path
import statistics
import sys

root, prefix, expected_count = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
output = root / "paired-summary.json"
if output.exists():
    raise SystemExit("refusing to overwrite summary")
rounds = sorted((root / "results").glob(prefix + "-*"))
if len(rounds) != expected_count:
    raise SystemExit(f"expected {expected_count} rounds, found {len(rounds)}")
pairs = []
for rd in rounds:
    record = {"round": rd.name}
    for label in ("base", "candidate"):
        d = rd / label
        result = json.loads((d / "result.json").read_text())
        samples = json.loads((d / "initial/resources.json").read_text())
        record[label] = {
            "seed": result["seed"],
            "rows": result["rows"],
            "dim": result["dim"],
            "queries": result["queries"],
            "workload_sha256": result["workload_sha256"],
            "image": result["image"],
            "times": result["times"],
            "memory_peak_bytes": max(int(s["files"]["memory.peak"]) for s in samples),
            "memory_events_final": samples[-1]["files"]["memory.events"],
            "io_stat_ready": samples[0]["files"]["io.stat"],
            "io_stat_pre_shutdown": samples[-1]["files"]["io.stat"],
            "oracle_checks": result["oracle_checks"],
            "recall": result["recall"],
            "maximum_distance_error": result["maximum_distance_error"],
        }
    a, b = record["base"], record["candidate"]
    if any(a[k] != b[k] for k in ("seed", "rows", "dim", "queries", "workload_sha256")):
        raise SystemExit(f"mismatched input for {rd.name}")
    if any(r["recall"] != 1.0 or r["oracle_checks"] != r["queries"] + 12 for r in (a, b)):
        raise SystemExit(f"failed/missing oracle checks in {rd.name}")
    record["query_reduction"] = 1.0 - b["times"]["query_s"] / a["times"]["query_s"]
    pairs.append(record)
summary = {
    "scope": "local alternating Docker pairs; not official scores",
    "pairs": pairs,
    "median_paired_query_reduction": statistics.median(p["query_reduction"] for p in pairs),
    "faster_query_pairs": sum(p["query_reduction"] > 0 for p in pairs),
    "total_oracle_checks": sum(p[k]["oracle_checks"] for p in pairs for k in ("base", "candidate")),
    "memory_peak_median": {k: statistics.median(p[k]["memory_peak_bytes"] for p in pairs) for k in ("base", "candidate")},
    "memory_peak_max": {k: max(p[k]["memory_peak_bytes"] for p in pairs) for k in ("base", "candidate")},
    "io_limitation": "ready to pre_shutdown raw io.stat only; not complete lifecycle physical device I/O",
}
output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "pairs"}, indent=2))
