#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
run_dir=$PWD/validation/local-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export PYTHONPATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/python3/dist-packages
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/blas:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu/lapack:/mnt/e/MiniVectorDB/deps/numpy-root/usr/lib/x86_64-linux-gnu
export OPENBLAS_NUM_THREADS=1
python3 "$run_dir/prepare_pair.py" || exit 1
context=/mnt/e/MiniVectorDB/runtime-context
mkdir -p "$context/lib/x86_64-linux-gnu" "$context/lib64"
for name in libstdc++.so.6 libm.so.6 libgcc_s.so.1 libc.so.6; do
  cp -L "/lib/x86_64-linux-gnu/$name" "$context/lib/x86_64-linux-gnu/$name" || exit 1
done
cp -L /lib64/ld-linux-x86-64.so.2 "$context/lib64/ld-linux-x86-64.so.2" || exit 1
cat > "$context/Dockerfile" <<'EOF'
FROM scratch
COPY lib/ /lib/
COPY lib64/ /lib64/
EOF
tag=codex-minivectordb-hmy-runtime:20261109
docker build -t "$tag" "$context" > "$run_dir/runtime-image-build.txt" 2>&1 || exit 1
image=$(docker image inspect "$tag" --format '{{.Id}}') || exit 1
socket=$(docker context inspect "$(docker context show)" --format '{{.Endpoints.docker.Host}}') || exit 1
printf 'image=%s\nsocket=%s\n' "$image" "$socket" > "$run_dir/runtime-image.txt"
output=/dev/shm/mvdb-hmy-paired-20261109
if test -e "$output"; then printf 'Refusing to reuse %s\n' "$output"; exit 1; fi
python3 "$run_dir/paired_tmpfs.py" \
  --baseline-binary /mnt/e/MiniVectorDB/build-release/minivectordb \
  --baseline-source "$PWD" \
  --baseline-manifest validation/cardinality-20261109/candidate-v2-production-manifest.json \
  --baseline-lock "$run_dir/control-lock.json" \
  --candidate-binary /mnt/e/MiniVectorDB/build-candidate/minivectordb \
  --candidate-source /mnt/e/MiniVectorDB/candidate-source \
  --candidate-manifest "$run_dir/candidate-manifest.json" \
  --benchmark-script tests/benchmark_local.py --oracle tests/audit_performance.py \
  --adapter tests/cardinality_probe.py --image "$image" --socket "$socket" \
  --cpuset auto --workloads vector128 --output-dir "$output" > "$run_dir/paired-run.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$run_dir/paired-run.txt"
if test -d "$output"; then
  python3 "$run_dir/copy_pair_evidence.py" "$output" "$run_dir/paired-output" > "$run_dir/paired-copy.txt" 2>&1 || exit 1
fi
exit "$status"
