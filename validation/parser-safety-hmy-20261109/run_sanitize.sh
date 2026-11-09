#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
out=validation/parser-safety-hmy-20261109
build=${BUILD_DIR:-"$root/build-parser-safety-sanitize"}
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
run sanitize-configure cmake -S . -B "$build" -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' || exit 1
run sanitize-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/sanitize-binary.sha256"
failed=0
run sanitize-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run sanitize-acceptance python3 tests/acceptance.py --binary "$build/minivectordb" -v || failed=1
run sanitize-optimization python3 tests/optimization_acceptance.py --binary "$build/minivectordb" -v || failed=1
exit "$failed"
