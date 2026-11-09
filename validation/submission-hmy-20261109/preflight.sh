#!/usr/bin/env bash
# Local preflight only. This does not invoke the organizer's evaluation.
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/submission-hmy-20261109
binary=${BINARY:-"$root/build-hmy-f/minivectordb"}
run() {
  local name=$1
  shift
  if test -e "$out/$name.txt"; then echo "Refusing to overwrite $out/$name.txt" >&2; return 1; fi
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
if ! test -x "$binary"; then echo "Release binary unavailable: $binary" >&2; exit 1; fi
sha256sum "$binary" > "$out/release-binary.sha256"
failed=0
run ctest ctest --test-dir "$(dirname "$binary")" --output-on-failure || failed=1
run agent-material python3 tests/test_agent_material.py -v || failed=1
run public-bridge-unit python3 tests/test_public_bridge.py || failed=1
run optimization python3 tests/optimization_acceptance.py --binary "$binary" -v || failed=1
run public-samples python3 tests/public_samples.py --binary "$binary" --package validation/exact-query-li-20261109/public-package/mysqltest --output "$out/public-samples.json" || failed=1
run historical-manifests python3 tools/handoff/verify.py || failed=1
run previous-evidence python3 validation/agent-learning-hmy-20261109/check_previous_evidence.py || failed=1
exit "$failed"
