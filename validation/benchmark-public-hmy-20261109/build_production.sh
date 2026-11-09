#!/usr/bin/env bash
set -uo pipefail
cd /mnt/e/MiniVectorDB/work
out=validation/benchmark-public-hmy-20261109
tag=codex-minivectordb-production-hmy:20261109
timeout 420 docker build --progress plain -t "$tag" . > "$out/docker-production-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/docker-production-build.txt"
if [ "$status" -eq 0 ]; then
  docker image inspect "$tag" > "$out/docker-production-image.json"
fi
exit "$status"
