#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110
if test "$#" -ne 3; then echo "Usage: $0 LABEL IMAGE NATIVE" >&2; exit 2; fi
label=$1; image=$2; native=$3
case "$label" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
log="$out/$label-image-binary.txt"
if test -e "$log"; then echo 'Refusing to overwrite image binary evidence' >&2; exit 1; fi
container=$(docker create "$image") || exit 1
temp=$(mktemp -d /dev/shm/mvdb-hmy-image-XXXXXX) || exit 1
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
