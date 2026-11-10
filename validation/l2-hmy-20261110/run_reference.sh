#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
if test "$#" -ne 2; then echo "Usage: $0 LABEL BINARY" >&2; exit 2; fi
label=$1
binary=$2
case "$label" in *[!a-zA-Z0-9_-]*|'') exit 2;; esac
log="$out/$label-reference.txt"
if test -e "$log"; then echo 'Refusing to overwrite reference result' >&2; exit 1; fi
python3 "$root/tests/optimization_acceptance.py" --binary "$binary" -v CacheAndIndexAcceptance.test_topk_reference_at_distance_loop_boundaries > "$log" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$log"
exit "$status"
