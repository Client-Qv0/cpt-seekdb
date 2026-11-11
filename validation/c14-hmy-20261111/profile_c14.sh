#!/usr/bin/env bash
set -uo pipefail
root=/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111
out="$root/validation/c14-hmy-20261111"
scratch=/var/tmp/mvdb-hmy-c14-profile-20261111
fixture="$out/c14-b68-screen/results/workload-71003-10000-128-1000/workload.json.gz"
binary=/mnt/e/MiniVectorDB/build-hmy-c14-team-20261111/minivectordb
perf=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110/unpacked/usr/lib/linux-tools-6.8.0-71/perf
export LD_LIBRARY_PATH=/mnt/e/MiniVectorDB/deps/hmy-l2-perf-20261110/unpacked/usr/lib/x86_64-linux-gnu
if test -e "$scratch" || test -e "$out/c14-profile-record.txt"; then echo 'refusing to overwrite profile' >&2; exit 1; fi
mkdir -p "$scratch/db"
python3 - "$fixture" "$scratch" > "$out/c14-profile-inputs.txt" <<'PY'
import gzip, hashlib, json, pathlib, sys
source, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
with gzip.open(source, "rt") as stream:
    workload=json.load(stream)
assert workload["rows"]==10000 and workload["dim"]==128 and len(workload["queries"])==1000
def request(i,sql):
    return json.dumps({"id":i,"op":"execute","sql":sql,"search_mode":"exact"},separators=(",",":"))+"\n"
load=request(1,workload["create"])
load+="".join(request(i+2,sql) for i,sql in enumerate(workload["batches"]))
load+=json.dumps({"id":200,"op":"shutdown"},separators=(",",":"))+"\n"
queries="".join(request(i+1,sql) for i,sql in enumerate(workload["queries"]*5))
queries+=json.dumps({"id":6000,"op":"shutdown"},separators=(",",":"))+"\n"
for name,text in (("load.jsonl",load),("queries.jsonl",queries)):
    raw=text.encode()
    (dest/name).write_bytes(raw)
    print(name,len(raw),hashlib.sha256(raw).hexdigest())
print("fixture",hashlib.sha256(source.read_bytes()).hexdigest())
PY
if test "$?" -ne 0; then exit 1; fi
sha256sum "$binary" >> "$out/c14-profile-inputs.txt"
"$binary" --data-dir "$scratch/db" < "$scratch/load.jsonl" > "$scratch/load.out" 2> "$out/c14-profile-load.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/c14-profile-load.txt"
if test "$status" -ne 0; then exit "$status"; fi
python3 - "$scratch/load.out" <<'PY'
import json,sys
lines=[json.loads(x) for x in open(sys.argv[1])]
assert len(lines)==103 and lines[0]=={"type":"ready"} and all(x.get("ok") is True for x in lines[1:])
PY
if test "$?" -ne 0; then exit 1; fi
"$perf" record -e cpu-clock:u -F 199 -o "$out/c14-profile.data" -- "$binary" --data-dir "$scratch/db" < "$scratch/queries.jsonl" > "$scratch/queries.out" 2> "$out/c14-profile-record.txt"
status=$?
printf 'exit=%s\n' "$status" >> "$out/c14-profile-record.txt"
if test "$status" -ne 0; then exit "$status"; fi
python3 - "$scratch/queries.out" >> "$out/c14-profile-record.txt" <<'PY'
import json,sys
count=0
for line in open(sys.argv[1]):
    obj=json.loads(line)
    if count==0: assert obj=={"type":"ready"}
    else: assert obj.get("ok") is True
    count+=1
assert count==5002,count
print("responses_checked",count)
PY
if test "$?" -ne 0; then exit 1; fi
"$perf" report --force --stdio --no-children --sort comm,dso,symbol -i "$out/c14-profile.data" > "$out/c14-profile-report.txt" 2>&1
status=$?
printf 'exit=%s\n' "$status" >> "$out/c14-profile-report.txt"
exit "$status"
