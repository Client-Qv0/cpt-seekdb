#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/docker-pin-hmy-20261110"
native=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
tag=codex-hmy-pinned-production:20261110
if test -e "$out/production-build.txt"; then echo 'Refusing to overwrite production evidence' >&2; exit 1; fi
cd "$root" || exit 1
cmp Dockerfile "$out/Dockerfile.candidate" || exit 1
sha256sum Dockerfile "$out/Dockerfile.candidate" > "$out/production-dockerfile.sha256"
docker build --progress=plain -t "$tag" . > "$out/production-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/production-build.txt"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/production-image.json" || exit 1
container=$(docker create "$tag") || exit 1
temp=$(mktemp -d /dev/shm/mvdb-pin-prod-XXXXXX) || exit 1
docker cp "$container:/app/minivectordb" "$temp/minivectordb"
status=$?
docker rm -v "$container" >/dev/null
if test "$status" -ne 0; then exit "$status"; fi
{
  docker image inspect "$tag" --format '{{.Id}}'
  sha256sum "$temp/minivectordb" "$native"
  cmp "$temp/minivectordb" "$native"
} > "$out/production-binary-comparison.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/production-binary-comparison.txt"
exit "$status"
