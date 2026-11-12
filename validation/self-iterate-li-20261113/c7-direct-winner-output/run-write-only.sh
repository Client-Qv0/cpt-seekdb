#!/usr/bin/env bash
set -euo pipefail
RUN=/home/li/mvdb-negative-local-20261113/c7-compact-output/write-only-20261113
BASE=/home/li/build-self-iterate-c2-base-20261113/minivectordb
CAND=/home/li/build-self-iterate-c2-20261113/minivectordb
SCRIPT=/home/li/mvdb-negative-local-20261113/c7-compact-output/benchmark_write_only.py
mkdir -p "$RUN"
run_one() {
  local variant=$1 pair=$2 bin=$BASE
  if [ "$variant" = candidate ]; then bin=$CAND; fi
  systemd-run --scope --quiet \
    --property=MemoryMax=134217728 \
    --property=MemorySwapMax=0 \
    --property=CPUQuota=200% \
    --property=AllowedCPUs=0-1 \
    python3 "$SCRIPT" --binary "$bin" > "$RUN/$variant-$pair.json"
}
for pair in 1 2 3 4 5 6; do
  if [ $((pair % 2)) -eq 1 ]; then
    run_one base "$pair"; run_one candidate "$pair"
  else
    run_one candidate "$pair"; run_one base "$pair"
  fi
done
python3 - "$RUN" <<'PY' > "$RUN/summary.json"

import json,statistics,sys

from pathlib import Path
run=Path(sys.argv[1]); rows=[]
for p in range(1,7):
 b=json.loads((run/f"base-{p}.json").read_text())
 c=json.loads((run/f"candidate-{p}.json").read_text())
 r=(b["write_seconds"]-c["write_seconds"])/b["write_seconds"]
 rows.append({"pair":p,"base":b["write_seconds"],"candidate":c["write_seconds"],"reduction":r,"candidate_win":c["write_seconds"]<b["write_seconds"]})
summary={"scope":"six alternating write-only A/B pairs; not official","pairs":6,"write_median_reduction":statistics.median(x["reduction"] for x in rows),"write_wins":sum(x["candidate_win"] for x in rows),"raw":rows}
print(json.dumps(summary,indent=2))
PY
