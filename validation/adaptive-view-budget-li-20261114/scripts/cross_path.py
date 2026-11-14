#!/usr/bin/env python3
"""Same queries on the same 50k table, dumped for a cross-path diff."""
import argparse, json, random, subprocess, sys
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--binary", required=True); p.add_argument("--data", required=True)
p.add_argument("--out", required=True); p.add_argument("--build", action="store_true")
a = p.parse_args()
proc = subprocess.Popen([str(Path(a.binary).resolve()), "--data-dir", a.data, "--dev-protocol"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True)
def sql(s):
    proc.stdin.write(s + "\n"); proc.stdin.flush()
    line = proc.stdout.readline()
    if not line: raise RuntimeError(proc.stderr.read())
    r = json.loads(line)
    if not r["ok"]: raise RuntimeError(r)
    return r
if a.build:
    rng = random.Random(3179)
    sql("CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR(128));")
    for begin in range(0, 50000, 100):
        t = []
        for i in range(begin, begin + 100):
            vec = json.dumps([round(rng.uniform(-1,1),6) for _ in range(128)], separators=(",",":"))
            t.append(f"({i},'g{i%5}','{vec}')")
        sql("INSERT INTO bench VALUES " + ",".join(t) + ";")
rng = random.Random(424242)
out = []
for i in range(12):
    vec = json.dumps([round(rng.uniform(-1,1),6) for _ in range(128)], separators=(",",":"))
    where = f" WHERE grp='g{i%5}'" if i % 2 else ""
    out.append(sql(f"SELECT id,grp,L2_DISTANCE(v,'{vec}') AS d FROM bench{where} ORDER BY d LIMIT 10")["rows"])
Path(a.out).write_text(json.dumps(out))
print(json.dumps({"queries": len(out)}))
