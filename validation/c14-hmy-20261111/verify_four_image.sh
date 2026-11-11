#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111/validation/c14-hmy-20261111
native=/mnt/e/MiniVectorDB/build-hmy-c14-four-20261111/minivectordb
image=codex-hmy-c14-four:20261111
log="$out/four-image-binary-check.txt"
if test -e "$log"; then echo 'refusing to overwrite image evidence' >&2; exit 1; fi
temp=$(mktemp -d /dev/shm/mvdb-c14-four-image-XXXXXX) || exit 1
container=$(docker create "$image") || exit 1
docker cp "$container:/app/minivectordb" "$temp/minivectordb"
status=$?
docker rm -v "$container" >/dev/null
if test "$status" -ne 0; then exit "$status"; fi
{
  docker image inspect "$image" --format '{{.Id}}'
  sha256sum "$temp/minivectordb" "$native"
  cmp "$temp/minivectordb" "$native"
} > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
