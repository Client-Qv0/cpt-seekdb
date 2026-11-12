#!/usr/bin/env bash
set -euo pipefail
RUN=/home/li/mvdb-negative-local-20261113/c13-statement-buffer/validation-20261113
REPO=/home/li/minivectordb-self-iterate-20261113
BASE=/home/li/build-self-iterate-c12-base-20261113/minivectordb
CAND=/home/li/build-self-iterate-c2-20261113/minivectordb
mkdir -p "$RUN"
{
  echo "scope=six-pair immediate-parent A/B, not official"
  echo "date=$(date --iso-8601=seconds)"
  echo "base_sha=$(sha256sum "$BASE" | awk '{print $1}')"
  echo "candidate_sha=$(sha256sum "$CAND" | awk '{print $1}')"
  echo "cgroup=MemoryMax=134217728 MemorySwapMax=0 CPUQuota=200% AllowedCPUs=0-1"
} > "$RUN/ab-environment.txt"
run_one() {
  local variant=$1 pair=$2 bin=$BASE
  if [ "$variant" = candidate ]; then bin=$CAND; fi
  systemd-run --scope --quiet --property=MemoryMax=134217728 \
    --property=MemorySwapMax=0 --property=CPUQuota=200% \
    --property=AllowedCPUs=0-1 python3 "$REPO/tests/benchmark_local.py" \
    --binary "$bin" > "$RUN/$variant-$pair.json" \
    2> "$RUN/$variant-$pair.stderr.log"
}
for pair in 1 2 3 4 5 6; do
  if [ $((pair % 2)) -eq 1 ]; then
    run_one base "$pair"; run_one candidate "$pair"
  else
    run_one candidate "$pair"; run_one base "$pair"
  fi
done
python3 /home/li/mvdb-negative-local-20261113/c7-compact-output/analyze_ab.py \
  "$RUN" > "$RUN/summary.json"
