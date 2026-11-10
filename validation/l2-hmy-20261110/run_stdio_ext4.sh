#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
base=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
data=/var/tmp/mvdb-hmy-l2-final-stdio-20261110
if test -e "$data" || test -e "$out/final-stdio-ext4.txt"; then echo 'Refusing to overwrite stdio evidence' >&2; exit 1; fi
python3 "$root/validation/perf-20261110-stdio/scripts/stdio_correctness.py" --baseline "$base" --candidate "$base" --output "$data" > "$out/final-stdio-ext4.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/final-stdio-ext4.txt"
if test "$status" -ne 0; then exit "$status"; fi
cp "$data/result.json" "$out/final-stdio-ext4-result.json"
cp "$data/baseline/trace.jsonl.gz" "$out/final-stdio-ext4-baseline-trace.jsonl.gz"
cp "$data/candidate/trace.jsonl.gz" "$out/final-stdio-ext4-candidate-trace.jsonl.gz"
