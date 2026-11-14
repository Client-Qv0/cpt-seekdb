#!/usr/bin/env python3
"""Equivalence check for the measured result-budget path.

Three views of the same data must agree on the top-20:
  narrow table, measured fast path (LIMIT 20)
  wide table,   measured fast path (LIMIT 20)
  both tables,  general path (LIMIT 5000, which is above the 4096 fast-path cap)

The general path accounts and spills per row, so its prefix is the oracle.
"""
import argparse
import json
import random
import subprocess
import tempfile
from pathlib import Path


def open_db(binary, directory):
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

    return proc, sql


def build(binary, directory, declared, rows, queries):
    proc, sql = open_db(binary, directory)
    rng = random.Random(3179)
    sql(f"CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR({declared}), v VECTOR(128));")
    for begin in range(0, rows, 100):
        tuples = []
        for i in range(begin, min(begin + 100, rows)):
            vec = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)],
                             separators=(",", ":"))
            tuples.append(f"({i},'g{i % 5}','{vec}')")
        sql("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
    filters = []
    for i in range(queries):
        vec = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)],
                         separators=(",", ":"))
        where = f" WHERE grp='g{i % 5}'" if i % 2 else ""
        filters.append((vec, where))
    return proc, sql, filters


def rows_for(sql, vec, where, limit):
    out = sql(f"SELECT id,grp,L2_DISTANCE(v,'{vec}') AS d FROM bench{where} ORDER BY d LIMIT {limit};")
    return out["rows"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True)
    p.add_argument("--rows", type=int, default=3000)
    p.add_argument("--queries", type=int, default=40)
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    binary = str(Path(a.binary).resolve())
    checked = 0
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        pn, sn, filters = build(binary, d1, 8, a.rows, a.queries)
        pw, sw, _ = build(binary, d2, 65535, a.rows, a.queries)
        try:
            for index, (vec, where) in enumerate(filters):
                top_narrow = rows_for(sn, vec, where, a.limit)
                top_wide = rows_for(sw, vec, where, a.limit)
                oracle_narrow = rows_for(sn, vec, where, 5000)[:a.limit]
                oracle_wide = rows_for(sw, vec, where, 5000)[:a.limit]
                for name, got in (("narrow/fast", top_narrow), ("wide/fast", top_wide),
                                  ("narrow/general", oracle_narrow),
                                  ("wide/general", oracle_wide)):
                    if got != top_narrow:
                        raise SystemExit(
                            f"MISMATCH query {index} {name}\n expected {top_narrow[:3]}\n got      {got[:3]}")
                if len(top_narrow) != a.limit:
                    raise SystemExit(f"short result on query {index}: {len(top_narrow)}")
                checked += 1
        finally:
            for proc in (pn, pw):
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
    print(json.dumps({"queries_checked": checked, "limit": a.limit, "rows": a.rows,
                      "identical": True}))


if __name__ == "__main__":
    main()
