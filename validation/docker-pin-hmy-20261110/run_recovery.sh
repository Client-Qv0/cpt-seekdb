#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/docker-pin-hmy-20261110"
if test "$#" -ne 2; then echo "Usage: $0 LABEL IMAGE" >&2; exit 2; fi
label=$1; image=$2
case "$label" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
log="$out/$label-recovery.txt"
data="/var/tmp/mvdb-pinned-recovery-$label-20261110"
if test -e "$log" || test -e "$data" || test -e "$out/$label-recovery"; then
  echo 'Refusing to overwrite recovery evidence' >&2; exit 1
fi
python3 "$root/tests/test_container_recovery.py" --image "$image" --data-root "$data" --output "$out/$label-recovery" > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
