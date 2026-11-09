#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=validation/local-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
cmake -S . -B /mnt/e/MiniVectorDB/build-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > "$run_dir/sanitize-build.txt" 2>&1 || exit 1
cmake --build /mnt/e/MiniVectorDB/build-sanitize --parallel 2 >> "$run_dir/sanitize-build.txt" 2>&1 || exit 1
sha256sum /mnt/e/MiniVectorDB/build-sanitize/minivectordb > "$run_dir/sanitize-binary.sha256"
ctest --test-dir /mnt/e/MiniVectorDB/build-sanitize --output-on-failure > "$run_dir/sanitize-ctest.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/sanitize-ctest.txt"
python3 tests/acceptance.py --binary /mnt/e/MiniVectorDB/build-sanitize/minivectordb -v > "$run_dir/sanitize-acceptance.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/sanitize-acceptance.txt"
python3 tests/optimization_acceptance.py --binary /mnt/e/MiniVectorDB/build-sanitize/minivectordb -v > "$run_dir/sanitize-optimization.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/sanitize-optimization.txt"
