#!/usr/bin/env bash
set -euo pipefail
RUN=$1; A=$2; B=$3; PAIRS=${4:-3}; MEM=${5:-134217728}
mkdir -p "$RUN"
run_one() {
  systemd-run --scope --quiet --property=MemoryMax="$MEM" \
    --property=MemorySwapMax=0 --property=CPUQuota=200% --property=AllowedCPUs=0-1 \
    python3 /tmp/probe_50k.py --binary "$3" --declared 8 --limit 10 \
      > "$RUN/$1-$2.json" 2>"$RUN/$1-$2.err"
}
for p in $(seq 1 "$PAIRS"); do
  if [ $((p % 2)) -eq 1 ]; then run_one before $p "$A"; run_one after $p "$B"
  else run_one after $p "$B"; run_one before $p "$A"; fi
done
python3 - "$RUN" "$PAIRS" <<'PY'
import json,sys,statistics,pathlib
run=pathlib.Path(sys.argv[1]); n=int(sys.argv[2])
b=[json.load(open(run/f"before-{p}.json"))["query_seconds"] for p in range(1,n+1)]
a=[json.load(open(run/f"after-{p}.json"))["query_seconds"] for p in range(1,n+1)]
d=[1-x/y for x,y in zip(a,b)]
print(f"50k rows TOPK 10: before {statistics.median(b):.3f}s -> after {statistics.median(a):.3f}s  median {statistics.median(d)*100:+.1f}%  wins {sum(1 for x in d if x>0)}/{n}")
print(f"  per query: {statistics.median(b)/20*1000:.1f}ms -> {statistics.median(a)/20*1000:.1f}ms")
print("  "+"  ".join(f"p{i}:{x*100:+.1f}%" for i,x in enumerate(d,1)))
PY
