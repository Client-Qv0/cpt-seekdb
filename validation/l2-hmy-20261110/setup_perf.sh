#!/usr/bin/env bash
set -uo pipefail
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110/perf-setup.txt
base=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110
if test -e "$base" || test -e "$out"; then echo 'Refusing to overwrite perf setup' >&2; exit 1; fi
mkdir -p "$base"
cd "$base" || exit 1
{
  apt-get download linux-tools-6.8.0-71 || exit 1
  sha256sum ./*.deb || exit 1
  dpkg-deb -x ./*.deb unpacked || exit 1
  find unpacked -type f -name perf -print
} > "$out" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out"
exit "$status"
