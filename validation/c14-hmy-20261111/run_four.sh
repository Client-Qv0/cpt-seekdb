#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
handoff="$out/teammate-handoff/evidence"
build=/mnt/e/MiniVectorDB/build-hmy-c14-four-20261111
baseline=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111/minivectordb
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$root/tests"
if test -e "$out/four-configure.txt" || test -e "$build"; then echo 'refusing to overwrite four-row evidence' >&2; exit 1; fi
export TMPDIR
TMPDIR=$(mktemp -d /dev/shm/mvdb-c14-four-XXXXXX) || exit 1
sha256sum "$root"/src/*.cpp "$root"/src/*.hpp "$root"/tests/test_exact_cache.cpp "$root"/Dockerfile "$root"/CMakeLists.txt > "$out/four-source.sha256"
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run four-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run four-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/four-binary.sha256"
failed=0
run four-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run four-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || failed=1
run four-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || failed=1
run four-differential python3 "$handoff/candidate-tests/distance_differential.py" --baseline "$baseline" --candidate "$build/minivectordb" --output "$out/four-differential.json" || failed=1
run four-float-edges python3 "$handoff/tests/float_parse_edges.py" --baseline "$baseline" --candidate "$build/minivectordb" --output /var/tmp/mvdb-hmy-four-float-20261111 || failed=1
run four-sql-batch8 python3 "$handoff/tests/sql_batch8_edges.py" --baseline "$baseline" --candidate "$build/minivectordb" --output /var/tmp/mvdb-hmy-four-sqlbatch8-20261111 || failed=1
run four-agent python3 "$root/tests/test_agent_material.py" -v || failed=1
exit "$failed"
