#!/usr/bin/env python3
"""Developer baseline only: not the official benchmark or cgroup accounting."""
import argparse
import json
import random
import resource
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", required=True)
    p.add_argument("--rows", type=int, default=10000)
    p.add_argument("--queries", type=int, default=1000)
    a = p.parse_args()
    binary = str(Path(a.binary).resolve())
    rng = random.Random(3179)
    with tempfile.TemporaryDirectory(prefix="mvdb-benchmark-") as directory:
        proc = subprocess.Popen([binary, "--data-dir", directory, "--dev-protocol"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

        def sql(statement):
            proc.stdin.write(statement + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("database stopped: " + proc.stderr.read())
            result = json.loads(line)
            if not result["ok"]:
                raise RuntimeError(result)
            return result

        try:
            sql("CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR(128));")
            batches = []
            for begin in range(0, a.rows, 100):
                tuples = []
                for i in range(begin, min(begin + 100, a.rows)):
                    vector = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)], separators=(",", ":"))
                    tuples.append(f"({i},'g{i % 5}','{vector}')")
                batches.append("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
            queries = []
            for i in range(a.queries):
                vector = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)], separators=(",", ":"))
                where = f" WHERE grp='g{i % 5}'" if i % 2 else ""
                queries.append(f"SELECT id,L2_DISTANCE(v,'{vector}') AS d FROM bench{where} ORDER BY d LIMIT 10;")
            start = time.perf_counter()
            for batch in batches:
                sql(batch)
            write_seconds = time.perf_counter() - start
            start = time.perf_counter()
            for query in queries:
                result = sql(query)
                assert len(result["rows"]) == min(10, a.rows if "WHERE" not in query else a.rows // 5)
                assert len({row[0] for row in result["rows"]}) == len(result["rows"])
                assert result["rows"] == sorted(result["rows"], key=lambda row: (row[1], row[0]))
            query_seconds = time.perf_counter() - start
            # VmHWM belongs to this executable after exec. RUSAGE_CHILDREN may
            # include the Python fork/exec startup footprint and hide a small
            # database's actual memory growth.
            status = Path(f"/proc/{proc.pid}/status").read_text()
            peak_rss = int(next(line.split()[1] for line in status.splitlines()
                                if line.startswith("VmHWM:")))
            proc.stdin.close()
            proc.wait(timeout=15)
            assert proc.returncode == 0, proc.stderr.read()
            files = sum(path.stat().st_size for path in Path(directory).rglob("*") if path.is_file())
            print(json.dumps({"scope": "local development baseline, not official scoring",
                              "rows": a.rows, "dimension": 128, "queries": a.queries,
                              "write_seconds": write_seconds, "query_seconds": query_seconds,
                              "data_file_bytes": files,
                              "peak_process_rss_kib": peak_rss,
                              "child_rusage_peak_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                              "not_measured": ["cgroup physical I/O", "cgroup memory peak", "official baseline ratio", "official hidden cases"],
                              "recall_note": "exact backend; this timing run checks count, uniqueness and sorting only"}, indent=2))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
