#!/usr/bin/env bash
set -uo pipefail
base=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110
out=/mnt/f/OceanBase/seekdb/cpt-seekdb/validation/l2-hmy-20261110/perf-dependency.txt
if test -e "$out"; then echo 'Refusing to overwrite evidence' >&2; exit 1; fi
cd "$base" || exit 1
apt-get download libtraceevent1 > "$out" 2>&1
status=$?
if test "$status" -eq 0; then
  sha256sum ./libtraceevent1_*.deb >> "$out"
  dpkg-deb -x ./libtraceevent1_*.deb unpacked >> "$out" 2>&1
  status=$?
fi
printf 'exit=%s\n' "$status" >> "$out"
exit "$status"
