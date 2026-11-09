#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
out=validation/local-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
cmake -S /mnt/e/MiniVectorDB/candidate-source -B /mnt/e/MiniVectorDB/build-candidate-sanitize -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined' > "$out/candidate-sanitize-build.txt" 2>&1 || exit 1
cmake --build /mnt/e/MiniVectorDB/build-candidate-sanitize --parallel 2 >> "$out/candidate-sanitize-build.txt" 2>&1 || exit 1
sha256sum /mnt/e/MiniVectorDB/build-candidate-sanitize/minivectordb > "$out/candidate-sanitize-binary.sha256"
ctest --test-dir /mnt/e/MiniVectorDB/build-candidate-sanitize --output-on-failure > "$out/candidate-sanitize-ctest.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$out/candidate-sanitize-ctest.txt"
python3 tests/optimization_acceptance.py --binary /mnt/e/MiniVectorDB/build-candidate-sanitize/minivectordb -v > "$out/candidate-sanitize-reference.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$out/candidate-sanitize-reference.txt"
python3 tests/acceptance.py --binary /mnt/e/MiniVectorDB/build-candidate-sanitize/minivectordb -v > "$out/candidate-sanitize-acceptance.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$out/candidate-sanitize-acceptance.txt"
