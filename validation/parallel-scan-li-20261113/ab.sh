#!/usr/bin/env bash
set -euo pipefail
RUN=$1; BASE=$2; CAND=$3; PAIRS=${4:-8}; Q=${5:-3000}
mkdir -p "$RUN"
run_one() {
  local variant=$1 pair=$2 bin=$BASE
  [ "$variant" = cand ] && bin=$CAND
  systemd-run --scope --quiet --property=MemoryMax=134217728 \
    --property=MemorySwapMax=0 --property=CPUQuota=200% \
    --property=AllowedCPUs=0-1 python3 tests/benchmark_local.py --binary "$bin" --queries "$Q" \
    > "$RUN/$variant-$pair.json" 2>"$RUN/$variant-$pair.err"
}
for pair in $(seq 1 "$PAIRS"); do
  if [ $((pair % 2)) -eq 1 ]; then run_one base $pair; run_one cand $pair
  else run_one cand $pair; run_one base $pair; fi
done
python3 - "$RUN" "$PAIRS" <<'PY'
import json,sys,statistics,pathlib
run=pathlib.Path(sys.argv[1]); n=int(sys.argv[2])
for metric in ("write_seconds","query_seconds"):
    d=[1-json.load(open(run/f"cand-{p}.json"))[metric]/json.load(open(run/f"base-{p}.json"))[metric] for p in range(1,n+1)]
    print(f"{metric}: median {statistics.median(d)*100:+.2f}%  wins {sum(1 for x in d if x>0)}/{n}  min {min(d)*100:+.2f}%  max {max(d)*100:+.2f}%")
PY
