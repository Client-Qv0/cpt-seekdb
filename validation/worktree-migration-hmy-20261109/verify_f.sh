#!/usr/bin/env bash
# Rebuild from the relocated F worktree. Configure PATH/LD_LIBRARY_PATH for
# CMake and PYTHONPATH for NumPy externally; never modify old evidence.
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/worktree-migration-hmy-20261109
build=${BUILD_DIR:-"$root/build-hmy-f"}
run() {
  local name=$1
  shift
  printf 'Command:' > "$out/$name.txt"
  printf ' %q' "$@" >> "$out/$name.txt"
  printf '\n' >> "$out/$name.txt"
  "$@" >> "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run configure cmake -S . -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/binary.sha256"
failed=0
run ctest ctest --test-dir "$build" --output-on-failure || failed=1
run public-bridge-unit python3 tests/test_public_bridge.py || failed=1
run benchmark-harness-unit python3 tests/test_benchmark_public_validation.py -v || failed=1
run optimization python3 tests/optimization_acceptance.py --binary "$build/minivectordb" -v || failed=1
run public-samples python3 tests/public_samples.py --binary "$build/minivectordb" --package validation/exact-query-li-20261109/public-package/mysqltest --output "$out/public-samples.json" || failed=1
exit "$failed"
