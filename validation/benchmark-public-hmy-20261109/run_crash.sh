#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
export TMPDIR=/dev/shm/mvdb-hmy-test
export PYTHONPATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/python3/dist-packages
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/blas:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/lapack:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu
export OPENBLAS_NUM_THREADS=1
out=validation/benchmark-public-hmy-20261109
python3 "$out/crash_after_writes.py" > "$out/crash-recovery.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/crash-recovery.txt"
exit "$status"
