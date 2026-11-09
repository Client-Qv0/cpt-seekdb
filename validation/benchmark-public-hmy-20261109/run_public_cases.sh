#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
out=validation/benchmark-public-hmy-20261109
export TMPDIR=/dev/shm/mvdb-hmy-test
export MVDB_PUBLIC_IMAGE=$(docker image inspect codex-minivectordb-production-hmy:20261109 --format '{{.Id}}')
chmod +x "$out/docker_public_wrapper.sh"
printf 'image=%s\n' "$MVDB_PUBLIC_IMAGE" > "$out/public-docker-image.txt"
python3 tests/public_samples.py --binary "$out/docker_public_wrapper.sh" \
  --package validation/exact-query-li-20261109/public-package/mysqltest \
  --output "$out/public-docker-cases.json" > "$out/public-docker-cases.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/public-docker-cases.txt"
exit "$status"
