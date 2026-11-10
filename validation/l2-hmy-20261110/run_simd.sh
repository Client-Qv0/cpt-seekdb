#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
build=/mnt/e/MiniVectorDB/build-hmy-l2-simd-20261110
base=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ! patch --dry-run --reverse --batch -p1 -d "$root" < "$out/simd-experiment.patch" >/dev/null 2>&1; then
  echo 'Apply the archived SIMD patch in an isolated checkout before building.' >&2; exit 1
fi
if test -e "$out/simd-configure.txt" || test -e "$build"; then echo 'Refusing to overwrite SIMD evidence' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run simd-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run simd-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/simd-binary.sha256"
failed=0
run simd-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run simd-differential python3 "$root/tests/distance_differential.py" --baseline "$base" --candidate "$build/minivectordb" --output "$out/differential-simd.json" || failed=1
run simd-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || failed=1
run simd-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || failed=1
exit "$failed"
