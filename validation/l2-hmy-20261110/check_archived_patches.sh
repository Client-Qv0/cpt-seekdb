#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
log="$out/archived-patches-check.txt"
if test -e "$log"; then echo 'Refusing to overwrite patch evidence' >&2; exit 1; fi
temp=$(mktemp -d /dev/shm/mvdb-hmy-patches-XXXXXX) || exit 1
status=0
for name in early-pruning simd; do
  mkdir -p "$temp/$name/src"
  cp "$root/src/engine.cpp" "$temp/$name/src/engine.cpp"
  patch --batch -p1 -d "$temp/$name" < "$out/$name-experiment.patch" >> "$log" 2>&1 || status=1
  patch --dry-run --reverse --batch -p1 -d "$temp/$name" < "$out/$name-experiment.patch" >> "$log" 2>&1 || status=1
  sha256sum "$temp/$name/src/engine.cpp" >> "$log"
done
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
