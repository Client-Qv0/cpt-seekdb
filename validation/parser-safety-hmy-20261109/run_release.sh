#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/parser-safety-hmy-20261109
build=${BUILD_DIR:-"$root/build-parser-safety"}
run() {
  local name=$1
  shift
  if test -e "$out/$name.txt"; then echo "Refusing to overwrite $name evidence" >&2; return 1; fi
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run release-configure cmake -S . -B "$build" -DCMAKE_BUILD_TYPE=Release || exit 1
run release-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/release-binary.sha256"
failed=0
run release-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run release-acceptance python3 tests/acceptance.py --binary "$build/minivectordb" --stress -v || failed=1
run release-optimization python3 tests/optimization_acceptance.py --binary "$build/minivectordb" --large -v || failed=1
run release-public-bridge python3 tests/test_public_bridge.py || failed=1
run release-public-samples python3 tests/public_samples.py --binary "$build/minivectordb" --package validation/exact-query-li-20261109/public-package/mysqltest --output "$out/release-public-samples.json" || failed=1
run release-agent-material python3 tests/test_agent_material.py -v || failed=1
exit "$failed"
