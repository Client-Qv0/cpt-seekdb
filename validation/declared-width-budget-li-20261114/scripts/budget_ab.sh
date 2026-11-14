#!/usr/bin/env bash
set -euo pipefail
RUN=$1; BIN=$2; LIMIT=$3; PAIRS=${4:-8}
mkdir -p "$RUN"
run_one() {  # variant pair declared
  systemd-run --scope --quiet --property=MemoryMax=134217728 \
    --property=MemorySwapMax=0 --property=CPUQuota=200% --property=AllowedCPUs=0-1 \
    python3 /tmp/probe_budget.py --binary "$BIN" --declared "$3" --limit "$LIMIT" \
    > "$RUN/$1-$2.json" 2>"$RUN/$1-$2.err"
}
for pair in $(seq 1 "$PAIRS"); do
  if [ $((pair % 2)) -eq 1 ]; then run_one narrow $pair 8; run_one wide $pair 65535
  else run_one wide $pair 65535; run_one narrow $pair 8; fi
done
python3 - "$RUN" "$PAIRS" "$LIMIT" <<'PY'
import json,sys,statistics,pathlib
run=pathlib.Path(sys.argv[1]); n=int(sys.argv[2]); lim=sys.argv[3]
nb=64+(64+4*8); wb=64+(64+4*65535)
BUD=4*1024*1024
print(f"LIMIT {lim}: narrow bound={64+nb} {'ON ' if 64+nb<=BUD//int(lim) else 'OFF'} | wide bound={64+wb} {'ON ' if 64+wb<=BUD//int(lim) else 'OFF'}")
d=[1-json.load(open(run/f"wide-{p}.json"))["query_seconds"]/json.load(open(run/f"narrow-{p}.json"))["query_seconds"] for p in range(1,n+1)]
nbq=statistics.median([json.load(open(run/f"narrow-{p}.json"))["query_seconds"] for p in range(1,n+1)])
wbq=statistics.median([json.load(open(run/f"wide-{p}.json"))["query_seconds"] for p in range(1,n+1)])
print(f"narrow median {nbq:.3f}s | wide median {wbq:.3f}s | wide vs narrow median {statistics.median(d)*100:+.2f}% wins {sum(1 for x in d if x>0)}/{n}")
print("  "+"  ".join(f"p{i}:{x*100:+.1f}%" for i,x in enumerate(d,1)))
PY
