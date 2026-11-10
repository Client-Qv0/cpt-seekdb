#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
base=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
early=/mnt/e/MiniVectorDB/build-hmy-l2-candidate-20261110/minivectordb
simd=/mnt/e/MiniVectorDB/build-hmy-l2-simd-20261110/minivectordb
if test -e "$out/final-optimization.txt"; then echo 'Refusing to overwrite final evidence' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
failed=0
run final-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$base" --large -v || failed=1
for name in baseline early simd; do
  case "$name" in baseline) exe="$base";; early) exe="$early";; simd) exe="$simd";; esac
  run "final-diff-$name" python3 "$root/tests/distance_differential.py" --baseline "$base" --candidate "$exe" --output "$out/final-diff-$name.json" || failed=1
done
run final-stdio python3 "$root/validation/perf-20261110-stdio/scripts/stdio_correctness.py" --baseline "$base" --candidate "$base" --output "$out/final-stdio-results" || failed=1
run final-agent python3 "$root/tests/test_agent_material.py" -v || failed=1
exit "$failed"
