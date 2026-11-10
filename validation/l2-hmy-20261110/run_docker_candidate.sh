#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
tag=codex-hmy-l2-candidate:20261110
if ! patch --dry-run --reverse --batch -p1 -d "$root" < "$out/early-pruning-experiment.patch" >/dev/null 2>&1; then
  echo 'Apply the archived early-pruning patch in an isolated checkout before building.' >&2; exit 1
fi
if test -e "$out/candidate-docker-build.txt"; then echo 'Refusing to overwrite Docker evidence' >&2; exit 1; fi
docker build --progress=plain -t "$tag" "$root" > "$out/candidate-docker-build.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/candidate-docker-build.txt"
if test "$status" -ne 0; then exit "$status"; fi
docker image inspect "$tag" > "$out/candidate-docker-image.json"
