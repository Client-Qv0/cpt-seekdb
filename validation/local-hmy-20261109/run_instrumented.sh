#!/usr/bin/env bash
set -euo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=$PWD/validation/local-hmy-20261109
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
python3 "$run_dir/prepare_instrumented.py" > "$run_dir/instrumented-build.txt"
cmake -S /mnt/e/MiniVectorDB/profile-source -B /mnt/e/MiniVectorDB/build-instrumented -DCMAKE_BUILD_TYPE=Release >> "$run_dir/instrumented-build.txt" 2>&1
cmake --build /mnt/e/MiniVectorDB/build-instrumented --parallel 2 >> "$run_dir/instrumented-build.txt" 2>&1
sha256sum /mnt/e/MiniVectorDB/build-instrumented/minivectordb /mnt/e/MiniVectorDB/profile-source/src/engine.cpp > "$run_dir/instrumented.sha256"
/mnt/e/MiniVectorDB/build-instrumented/minivectordb --dev-protocol --data-dir /dev/shm/mvdb-hmy-profile-db < "$run_dir/profile-query.sql" > "$run_dir/instrumented-output.jsonl" 2> "$run_dir/instrumented-profile.txt"
