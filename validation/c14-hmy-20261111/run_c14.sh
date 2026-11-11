#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
handoff="$out/teammate-handoff/evidence"
build=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111
baseline=/mnt/e/MiniVectorDB/build-hmy-c14-base-20261111/minivectordb
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if test -e "$out/c14-configure.txt" || test -e "$build"; then echo 'refusing to overwrite C14 evidence' >&2; exit 1; fi
export TMPDIR
TMPDIR=$(mktemp -d /dev/shm/mvdb-c14-team-XXXXXX) || exit 1
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run c14-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run c14-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/c14-binary.sha256"
failed=0
run c14-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run c14-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || failed=1
run c14-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || failed=1
run c14-differential python3 "$handoff/candidate-tests/distance_differential.py" --baseline "$baseline" --candidate "$build/minivectordb" --output "$out/c14-differential.json" || failed=1
run c14-float-edges python3 "$handoff/tests/float_parse_edges.py" --baseline "$baseline" --candidate "$build/minivectordb" --output /var/tmp/mvdb-hmy-c14-float-20261111 || failed=1
run c14-sql-edges python3 "$handoff/candidate-tests/sql_lane_edges.py" --baseline "$baseline" --candidate "$build/minivectordb" --output /var/tmp/mvdb-hmy-c14-sql-20261111 || failed=1
exit "$failed"
