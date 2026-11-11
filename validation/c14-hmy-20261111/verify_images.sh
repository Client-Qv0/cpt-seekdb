#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111/validation/c14-hmy-20261111
if test -e "$out/images-binary-check.txt"; then echo 'refusing to overwrite image evidence' >&2; exit 1; fi
temp=$(mktemp -d /dev/shm/mvdb-c14-image-XXXXXX) || exit 1
status=0
for label in baseline team; do
  case "$label" in
    baseline) image=codex-hmy-c14-baseline:20261111; native=/mnt/e/MiniVectorDB/build-hmy-c14-base-20261111/minivectordb;;
    team) image=codex-hmy-c14-team:20261111; native=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111/minivectordb;;
  esac
  container=$(docker create "$image") || exit 1
  docker cp "$container:/app/minivectordb" "$temp/$label"
  copied=$?
  docker rm -v "$container" >/dev/null
  if test "$copied" -ne 0; then exit "$copied"; fi
  {
    printf '%s\n' "$label"
    docker image inspect "$image" --format '{{.Id}}'
    sha256sum "$temp/$label" "$native"
    cmp "$temp/$label" "$native"
  } >> "$out/images-binary-check.txt" 2>&1 || status=1
done
printf 'exit=%s\n' "$status" >> "$out/images-binary-check.txt"
exit "$status"
