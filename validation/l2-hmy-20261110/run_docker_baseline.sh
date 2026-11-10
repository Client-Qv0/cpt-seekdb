#!/usr/bin/env bash
set -uo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/validation/l2-hmy-20261110"
tag=codex-hmy-l2-baseline:20261110
if test -e "$out/baseline-docker-build.txt"; then echo 'Refusing to overwrite Docker evidence' >&2; exit 1; fi
docker build --progress=plain -t "$tag" "$root" > "$out/baseline-docker-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/baseline-docker-build.txt"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/baseline-docker-image.json"
