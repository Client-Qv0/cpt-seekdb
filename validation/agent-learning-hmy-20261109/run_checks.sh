#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/agent-learning-hmy-20261109
run() {
  local name=$1
  shift
  if test -e "$out/$name.txt"; then echo "Refusing to overwrite $out/$name.txt" >&2; return 1; fi
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  cat "$out/$name.txt"
  return "$status"
}
failed=0
run material-check python3 tests/test_agent_material.py -v || failed=1
run previous-evidence-check python3 "$out/check_previous_evidence.py" || failed=1
run handoff-check python3 tools/handoff/verify.py || failed=1
exit "$failed"
