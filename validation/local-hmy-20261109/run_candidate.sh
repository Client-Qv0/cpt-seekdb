#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=validation/local-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/lib/x86_64-linux-gnu
export PATH=/mnt/e/MiniVectorDB/deps/cmake-root/usr/bin:$PATH
cmake -S /mnt/e/MiniVectorDB/candidate-source -B /mnt/e/MiniVectorDB/build-candidate -DCMAKE_BUILD_TYPE=Release > "$run_dir/candidate-build.txt" 2>&1 || exit 1
cmake --build /mnt/e/MiniVectorDB/build-candidate --parallel 2 >> "$run_dir/candidate-build.txt" 2>&1 || exit 1
sha256sum /mnt/e/MiniVectorDB/build-candidate/minivectordb /mnt/e/MiniVectorDB/candidate-source/src/engine.cpp > "$run_dir/candidate.sha256"
for variant in release candidate; do
  python3 tests/optimization_acceptance.py --binary "/mnt/e/MiniVectorDB/build-$variant/minivectordb" -v > "$run_dir/$variant-reference.txt" 2>&1
  printf 'exit=%s\n' "$?" >> "$run_dir/$variant-reference.txt"
done
ctest --test-dir /mnt/e/MiniVectorDB/build-candidate --output-on-failure > "$run_dir/candidate-ctest.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/candidate-ctest.txt"
python3 tests/acceptance.py --binary /mnt/e/MiniVectorDB/build-candidate/minivectordb -v > "$run_dir/candidate-acceptance.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/candidate-acceptance.txt"
python3 tests/public_samples.py --binary /mnt/e/MiniVectorDB/build-candidate/minivectordb --package validation/exact-query-li-20261109/public-package/mysqltest --output "$run_dir/candidate-public.json" > "$run_dir/candidate-public.txt" 2>&1
printf 'exit=%s\n' "$?" >> "$run_dir/candidate-public.txt"
