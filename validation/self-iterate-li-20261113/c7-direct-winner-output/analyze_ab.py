#!/usr/bin/env python3
import json
import statistics
import sys
from pathlib import Path

run = Path(sys.argv[1])
metrics = ["write_seconds", "query_seconds", "data_file_bytes",
           "peak_process_rss_kib", "child_rusage_peak_kib"]
summary = {
    "scope": "six alternating local A/B pairs in fresh 2-CPU, 128-MiB, zero-swap cgroups; not official",
    "pairs": 6,
    "metrics": {},
    "raw": [],
}
for pair in range(1, 7):
    base = json.loads((run / f"base-{pair}.json").read_text())
    candidate = json.loads((run / f"candidate-{pair}.json").read_text())
    record = {"pair": pair}
    for metric in metrics:
        b = base[metric]
        c = candidate[metric]
        reduction = (b - c) / b if b else 0.0
        record[metric] = {"base": b, "candidate": c,
                          "reduction": reduction, "candidate_win": c < b}
    summary["raw"].append(record)
for metric in metrics:
    reductions = [record[metric]["reduction"] for record in summary["raw"]]
    summary["metrics"][metric] = {
        "paired_reductions": reductions,
        "median_reduction": statistics.median(reductions),
        "candidate_wins": sum(record[metric]["candidate_win"] for record in summary["raw"]),
    }
query = summary["metrics"]["query_seconds"]
write = summary["metrics"]["write_seconds"]
memory = summary["metrics"]["peak_process_rss_kib"]
summary["gate"] = {
    "required_query_median_reduction": 0.02,
    "required_query_wins": 5,
    "max_allowed_write_regression": 0.02,
    "max_allowed_memory_regression": 0.02,
    "query_passed": query["median_reduction"] >= 0.02 and query["candidate_wins"] >= 5,
    "write_passed": write["median_reduction"] >= -0.02,
    "memory_passed": memory["median_reduction"] >= -0.02,
}
summary["gate"]["passed"] = all(
    summary["gate"][key] for key in ("query_passed", "write_passed", "memory_passed"))
print(json.dumps(summary, indent=2))
