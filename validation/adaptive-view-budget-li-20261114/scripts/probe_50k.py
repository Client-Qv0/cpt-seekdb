#!/usr/bin/env python3
"""Isolate the projection_bound result-budget gate.

Same 10k rows, same 128-dim vectors, same SQL shape. The only difference is
the *declared* width of the projected VARCHAR column, which is the only thing
that moves projection_bound. Run at a fixed LIMIT so the workload is identical.
"""
import argparse
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True)
    p.add_argument("--declared", type=int, required=True, help="VARCHAR(n) in DDL")
    p.add_argument("--limit", type=int, required=True)
    p.add_argument("--rows", type=int, default=50000)
    p.add_argument("--queries", type=int, default=200)
    a = p.parse_args()

    binary = str(Path(a.binary).resolve())
    rng = random.Random(3179)
    with tempfile.TemporaryDirectory(prefix="mvdb-probe-") as directory:
        proc = subprocess.Popen([binary, "--data-dir", directory, "--dev-protocol"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

        def sql(statement):
            proc.stdin.write(statement + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("db stopped: " + proc.stderr.read())
            result = json.loads(line)
            if not result["ok"]:
                raise RuntimeError(result)
            return result

        try:
            sql(f"CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR({a.declared}), v VECTOR(128));")
            batches = []
            for begin in range(0, a.rows, 100):
                tuples = []
                for i in range(begin, min(begin + 100, a.rows)):
                    vec = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)],
                                     separators=(",", ":"))
                    tuples.append(f"({i},'g{i % 5}','{vec}')")
                batches.append("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
            queries = []
            for _ in range(a.queries):
                vec = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)],
                                 separators=(",", ":"))
                queries.append(
                    f"SELECT id,grp,L2_DISTANCE(v,'{vec}') AS d FROM bench "
                    f"ORDER BY d LIMIT {a.limit};")
            for batch in batches:
                sql(batch)
            start = time.perf_counter()
            for query in queries:
                rows = sql(query)["rows"]
                assert len(rows) == a.limit, (len(rows), a.limit)
            query_seconds = time.perf_counter() - start
            hwm = 0
            for line in Path(f"/proc/{proc.pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    hwm = int(line.split()[1])
            print(json.dumps({"declared": a.declared, "limit": a.limit,
                              "query_seconds": query_seconds,
                              "peak_rss_kib": hwm}))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
