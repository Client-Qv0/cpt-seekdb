#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c22-hmy-20261111"
build=/mnt/e/MiniVectorDB/build-hmy-c22-sanitize-20261111
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR=$(mktemp -d /dev/shm/mvdb-c22-san-XXXXXX)
cmake -S "$root" -B "$build" -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > "$out/san-configure.txt" 2>&1 || exit 1
cmake --build "$build" --parallel 2 > "$out/san-build.txt" 2>&1 || exit 1
ctest --test-dir "$build" --output-on-failure > "$out/san-ctest.txt" 2>&1
status=$?
echo "exit=$status" >> "$out/san-ctest.txt"
cat "$out/san-ctest.txt"
exit "$status"
