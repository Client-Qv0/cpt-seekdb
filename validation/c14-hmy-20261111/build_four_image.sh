#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
tag=codex-hmy-c14-four:20261111
if test -e "$out/four-docker-build.txt"; then echo 'refusing to overwrite four-row image evidence' >&2; exit 1; fi
docker build --progress=plain -t "$tag" "$root" > "$out/four-docker-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/four-docker-build.txt"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/four-image.json"
