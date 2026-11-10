#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/docker-pin-hmy-20261110"
baseline=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
if test "$#" -ne 1; then echo "Usage: $0 LABEL" >&2; exit 2; fi
label=$1
case "$label" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
log="$out/$label-build.txt"
tag="codex-hmy-pinned-$label:20261110"
if test -e "$log"; then echo 'Refusing to overwrite build evidence' >&2; exit 1; fi
cd "$root" || exit 1
{
  date --iso-8601=seconds
  docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
  sha256sum "$out/Dockerfile.candidate" CMakeLists.txt src/*.cpp src/*.hpp
} > "$out/$label-inputs.txt" 2>&1
timeout 480 docker build --no-cache --progress=plain -f "$out/Dockerfile.candidate" -t "$tag" . > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/$label-image.json" || exit 1
container=$(docker create "$tag") || exit 1
temp=$(mktemp -d /dev/shm/mvdb-hmy-pinned-XXXXXX) || exit 1
docker cp "$container:/app/minivectordb" "$temp/minivectordb"
status=$?
docker rm -v "$container" >/dev/null
if test "$status" -ne 0; then exit "$status"; fi
{
  docker image inspect "$tag" --format '{{.Id}}'
  sha256sum "$temp/minivectordb" "$baseline"
  cmp "$temp/minivectordb" "$baseline"
} > "$out/$label-binary-comparison.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/$label-binary-comparison.txt"
exit "$status"
