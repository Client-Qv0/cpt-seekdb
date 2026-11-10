#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
build=/mnt/e/MiniVectorDB/build-hmy-l2-candidate-20261110
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ! patch --dry-run --reverse --batch -p1 -d "$root" < "$out/early-pruning-experiment.patch" >/dev/null 2>&1; then
  echo 'Apply the archived early-pruning patch in an isolated checkout before building.' >&2; exit 1
fi
if test -e "$out/candidate-configure.txt" || test -e "$build"; then echo 'Refusing to overwrite candidate evidence' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run candidate-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run candidate-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/candidate-binary.sha256"
failed=0
run candidate-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run candidate-reference-run bash "$out/run_reference.sh" candidate-standalone "$build/minivectordb" || failed=1
run candidate-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" --stress -v || failed=1
run candidate-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" --large -v || failed=1
exit "$failed"
