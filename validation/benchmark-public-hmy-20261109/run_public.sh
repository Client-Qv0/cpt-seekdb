#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
out=validation/benchmark-public-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export PYTHONPATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/python3/dist-packages
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/blas:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/lapack:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu
export OPENBLAS_NUM_THREADS=1
seed=${1:?seed required}
rounds=${2:?round count required}
name=${3:-seed-$seed}
case "$name" in *[!a-zA-Z0-9_-]*|'') echo 'Invalid output name' >&2; exit 2;; esac
if [ -e "$out/$name" ] || [ -e "$out/$name.log.txt" ]; then
  echo "Refusing to overwrite existing evidence: $name" >&2
  exit 1
fi
python3 tests/benchmark_public_validation.py \
  --binary /mnt/e/MiniVectorDB/production-image-minivectordb \
  --image codex-minivectordb-production-hmy:20261109 \
  --source . --manifest validation/cardinality-20261109/candidate-v2-production-manifest.json \
  --output "$out/$name" --data-parent /var/tmp --seed "$seed" --rounds "$rounds" \
  > "$out/$name.log.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/$name.log.txt"
exit "$status"
