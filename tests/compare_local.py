#!/usr/bin/env python3
"""Paired local timing comparison. Does not compute contest score or cgroup cost."""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--rows", type=int, default=10000)
    p.add_argument("--queries", type=int, default=1000)
    a = p.parse_args()
    binaries = {k: Path(getattr(a, k)).resolve() for k in ("baseline", "candidate")}
    rounds = []
    for i in range(a.rounds):
        order = ["baseline", "candidate"] if i % 2 == 0 else ["candidate", "baseline"]
        item = {"order": order}
        for which in order:
            run = subprocess.run([sys.executable, str(Path(__file__).with_name("benchmark_local.py")),
                                  "--binary", str(binaries[which]), "--rows", str(a.rows),
                                  "--queries", str(a.queries)], text=True, capture_output=True, check=True)
            item[which] = json.loads(run.stdout)
        rounds.append(item)
        print(f"completed paired round {i + 1}/{a.rounds}", file=sys.stderr, flush=True)
    medians = {which: {metric: statistics.median(x[which][metric] for x in rounds)
                       for metric in ("write_seconds", "query_seconds", "peak_process_rss_kib", "data_file_bytes")}
               for which in binaries}
    print(json.dumps({"scope": "local native comparison only, not official ranking",
                      "binaries": {k: {"sha256": hashlib.sha256(v.read_bytes()).hexdigest()}
                                   for k, v in binaries.items()},
                      "rounds": rounds, "medians": medians,
                      "query_speedup": medians["baseline"]["query_seconds"] / medians["candidate"]["query_seconds"],
                      "write_speedup": medians["baseline"]["write_seconds"] / medians["candidate"]["write_seconds"],
                      "rss_ratio_candidate_to_baseline": medians["candidate"]["peak_process_rss_kib"] / medians["baseline"]["peak_process_rss_kib"],
                      "limitations": ["RSS excludes cgroup page-cache accounting", "data-file size is not physical I/O", "no official baseline or three-round E statistic"]}, indent=2))


if __name__ == "__main__":
    main()
