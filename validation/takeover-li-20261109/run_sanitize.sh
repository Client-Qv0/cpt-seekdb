#!/bin/sh
set -eu
cd /opt/minivectordb-hmy-li
p=validation/takeover-li-20261109
cmake -S . -B build-takeover-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > "$p/configure-sanitize.log" 2>&1
cmake --build build-takeover-sanitize --parallel 2 > "$p/build-sanitize.log" 2>&1
export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1
export UBSAN_OPTIONS=halt_on_error=1
ctest --test-dir build-takeover-sanitize --output-on-failure > "$p/ctest-sanitize.log" 2>&1
python3 tests/acceptance.py --binary "$PWD/build-takeover-sanitize/minivectordb" -v > "$p/acceptance-sanitize.log" 2>&1
python3 tests/optimization_acceptance.py --binary "$PWD/build-takeover-sanitize/minivectordb" -v > "$p/optimization-sanitize.log" 2>&1
echo 0 > "$p/sanitize.exit"
