#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111/validation/c14-hmy-20261111
build=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if test -e "$out/four-row-before.txt"; then echo 'refusing to overwrite evidence' >&2; exit 1; fi
cmake --build "$build" --target test_exact_cache --parallel 2 > "$out/four-row-before.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/four-row-before.txt"
if test "$status" -eq 0; then echo 'expected missing four-row helper to fail compilation' >&2; exit 1; fi
exit 0
