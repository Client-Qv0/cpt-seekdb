#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/parser-safety-hmy-20261109
run() {
  local name=$1
  shift
  if test -e "$out/$name.txt"; then echo "Refusing to overwrite $name" >&2; return 1; fi
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
failed=0
run release-acceptance-updated python3 tests/acceptance.py --binary "$root/build-parser-safety/minivectordb" --stress -v || failed=1
run sanitize-acceptance-updated python3 tests/acceptance.py --binary "$root/build-parser-safety-sanitize/minivectordb" -v || failed=1
exit "$failed"
