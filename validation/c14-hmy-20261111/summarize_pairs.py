#!/usr/bin/env python3
"""Summarize full paired rounds without discarding slow runs."""
import json
from pathlib import Path
import statistics
import sys

root, prefix, expected_count = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
dest = root / "paired-summary.json"
if dest.exists():
    raise SystemExit("refusing to overwrite summary")
rounds = sorted((root / "results").glob(prefix + "-*"))
if len(rounds) != expected_count:
    raise SystemExit(f"expected {expected_count} rounds; got {len(rounds)}")
pairs = []
for rd in rounds:
    item = {"round": rd.name}
    for label in ("base", "candidate"):
        d = rd / label
        result = json.loads((d / "result.json").read_text())
        samples = json.loads((d / "initial/resources.json").read_text())
        item[label] = {k: result[k] for k in ("seed", "rows", "dim", "queries", "image",
                       "times", "oracle_checks", "recall", "maximum_distance_error", "workload_sha256")}
        item[label]["memory_peak_bytes"] = max(int(s["files"]["memory.peak"]) for s in samples)
        item[label]["memory_events_final"] = samples[-1]["files"]["memory.events"]
        item[label]["io_stat_ready"] = samples[0]["files"]["io.stat"]
        item[label]["io_stat_pre_shutdown"] = samples[-1]["files"]["io.stat"]
    a, b = item["base"], item["candidate"]
    for key in ("seed", "rows", "dim", "queries", "workload_sha256"):
        if a[key] != b[key]:
            raise SystemExit(f"unmatched {key}: {rd.name}")
    if any(r["recall"] != 1.0 or r["oracle_checks"] != r["queries"] + 12 for r in (a,b)):
        raise SystemExit(f"missing oracle checks: {rd.name}")
    item["reductions"] = {k: 1.0-b["times"][k]/a["times"][k] for k in a["times"]}
    pairs.append(item)
keys = pairs[0]["reductions"]
metrics = {k: {"median_reduction": statistics.median(p["reductions"][k] for p in pairs),
               "reductions": [p["reductions"][k] for p in pairs],
               "faster_pairs": sum(p["reductions"][k] > 0 for p in pairs)} for k in keys}
summary = {"scope": "local paired tests; not official score", "pairs": pairs, "metrics": metrics,
           "oracle_checks": sum(p[k]["oracle_checks"] for p in pairs for k in ("base","candidate")),
           "memory_peak_median": {k: statistics.median(p[k]["memory_peak_bytes"] for p in pairs) for k in ("base","candidate")},
           "io_limitation": "ready through pre-shutdown only; not official complete lifecycle physical I/O"}
dest.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
print(json.dumps({"pairs": len(pairs), "query": metrics["query_s"],
                  "write": metrics["write_s"], "first": metrics["first_query_s"],
                  "restart_query": metrics["restart_query_s"], "oracle_checks": summary["oracle_checks"],
                  "memory_peak_median": summary["memory_peak_median"]}, indent=2))
