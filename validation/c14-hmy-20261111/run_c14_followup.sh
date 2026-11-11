#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
handoff="$out/teammate-handoff/evidence"
baseline=/mnt/e/MiniVectorDB/build-hmy-c14-base-20261111/minivectordb
candidate=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111/minivectordb
export PYTHONPATH="$root/tests"
export TMPDIR
TMPDIR=$(mktemp -d /dev/shm/mvdb-c14-retry-XXXXXX) || exit 1
if test -e "$out/c14-differential-retry.txt"; then echo 'refusing to overwrite retry evidence' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
failed=0
run c14-differential-retry python3 "$handoff/candidate-tests/distance_differential.py" --baseline "$baseline" --candidate "$candidate" --output "$out/c14-differential-retry.json" || failed=1
run c14-sql-batch8 python3 "$handoff/tests/sql_batch8_edges.py" --baseline "$baseline" --candidate "$candidate" --output /var/tmp/mvdb-hmy-c14-sqlbatch8-20261111 || failed=1
exit "$failed"
