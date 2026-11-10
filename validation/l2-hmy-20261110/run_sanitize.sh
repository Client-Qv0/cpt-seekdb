#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
build=/mnt/e/MiniVectorDB/build-hmy-l2-sanitize-20261110
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1
export UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
if test -e "$out/sanitize-configure.txt" || test -e "$build"; then echo 'Refusing to overwrite sanitizer evidence' >&2; exit 1; fi
run() {
  local name=$1; shift
  "$@" > "$out/$name.txt" 2>&1
  local status=$?
  printf 'exit=%s\n' "$status" >> "$out/$name.txt"
  printf '%s exit=%s\n' "$name" "$status"
  return "$status"
}
run sanitize-configure cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Debug '-DCMAKE_CXX_FLAGS=-fsanitize=address,undefined -fno-omit-frame-pointer' '-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined' || exit 1
run sanitize-build cmake --build "$build" --parallel 2 || exit 1
sha256sum "$build/minivectordb" > "$out/sanitize-binary.sha256"
failed=0
run sanitize-ctest ctest --test-dir "$build" --output-on-failure || failed=1
run sanitize-acceptance python3 "$root/tests/acceptance.py" --binary "$build/minivectordb" -v || failed=1
run sanitize-optimization python3 "$root/tests/optimization_acceptance.py" --binary "$build/minivectordb" -v || failed=1
exit "$failed"
