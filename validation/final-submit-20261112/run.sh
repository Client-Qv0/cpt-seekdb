#!/usr/bin/env bash
set -eu
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/final-submit-20261112"
export PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH"
export LD_LIBRARY_PATH="/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR=$(mktemp -d /dev/shm/mvdb-final-XXXXXX)
cmake --build /mnt/e/MiniVectorDB/build-hmy-c22-parser-20261111 --parallel 2 > "$out/build.txt" 2>&1
ctest --test-dir /mnt/e/MiniVectorDB/build-hmy-c22-parser-20261111 --output-on-failure > "$out/ctest.txt" 2>&1
sha256sum /mnt/e/MiniVectorDB/build-hmy-c22-parser-20261111/minivectordb > "$out/binary.sha256"
python3 "$root/tests/test_agent_material.py" -v > "$out/agent-material.txt" 2>&1
cat "$out/ctest.txt" "$out/binary.sha256"
