#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/cpt-seekdb
out="$root/validation/l2-hmy-20261110"
scratch=/var/tmp/mvdb-hmy-l2-profile-20261110
perf=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110/unpacked/usr/lib/linux-tools-6.8.0-71/perf
binary=/mnt/e/MiniVectorDB/build-hmy-l2-baseline-20261110/minivectordb
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110/unpacked/usr/lib/x86_64-linux-gnu
if test -e "$scratch" || test -e "$out/profile-record.txt"; then echo 'Refusing to overwrite profile' >&2; exit 1; fi
mkdir -p "$scratch/db"
python3 - "$root/validation/benchmark-public-hmy-20261109/seed-3179/workload.sql.gz" "$scratch" <<'PY'
import gzip, hashlib, pathlib, sys
src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
load, query = [], []
with gzip.open(src, "rt", encoding="utf8") as stream:
    for line in stream:
        (query if line.lstrip().upper().startswith("SELECT") else load).append(line)
if len(load) != 101 or len(query) != 1000:
    raise RuntimeError((len(load), len(query)))
for name, text in (("load.sql", "".join(load)), ("query.sql", "".join(query) * 5)):
    data = text.encode()
    (dest / name).write_bytes(data)
    print(name, len(data), hashlib.sha256(data).hexdigest())
print("source", hashlib.sha256(src.read_bytes()).hexdigest())
PY
if test "$?" -ne 0; then exit 1; fi
"$binary" --data-dir "$scratch/db" --dev-protocol < "$scratch/load.sql" > "$scratch/load-output.jsonl" 2> "$out/profile-load-stderr.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/profile-load-stderr.txt"
if test "$status" -ne 0; then exit "$status"; fi
python3 - "$scratch/load-output.jsonl" <<'PY'
import json, sys
rows = [json.loads(s) for s in open(sys.argv[1])]
assert len(rows) == 101 and all(row["ok"] for row in rows)
PY
if test "$?" -ne 0; then exit 1; fi
"$perf" record -e cpu-clock:u -F 199 -o "$out/profile.data" -- "$binary" --data-dir "$scratch/db" --dev-protocol < "$scratch/query.sql" > /dev/null 2> "$out/profile-record.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/profile-record.txt"
if test "$status" -ne 0; then exit "$status"; fi
"$perf" report --stdio --no-children --sort comm,dso,symbol -i "$out/profile.data" > "$out/profile-report.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/profile-report.txt"
exit "$status"
