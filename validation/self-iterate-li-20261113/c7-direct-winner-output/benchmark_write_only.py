#!/usr/bin/env python3
import argparse
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--binary", required=True)
parser.add_argument("--rows", type=int, default=10000)
args = parser.parse_args()
binary = str(Path(args.binary).resolve())
rng = random.Random(3179)
with tempfile.TemporaryDirectory(prefix="mvdb-write-only-") as directory:
    proc = subprocess.Popen(
        [binary, "--data-dir", directory, "--dev-protocol"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True)
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
        for begin in range(0, args.rows, 100):
            tuples = []
            for i in range(begin, min(begin + 100, args.rows)):
                vector = json.dumps(
                    [round(rng.uniform(-1, 1), 6) for _ in range(128)],
                    separators=(",", ":"))
                tuples.append(f"({i},'g{i % 5}','{vector}')")
            batches.append("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
        start = time.perf_counter()
        for batch in batches:
            sql(batch)
        write_seconds = time.perf_counter() - start
        status = Path(f"/proc/{proc.pid}/status").read_text()
        peak_rss = int(next(line.split()[1] for line in status.splitlines()
                            if line.startswith("VmHWM:")))
        proc.stdin.close()
        proc.wait(timeout=15)
        assert proc.returncode == 0, proc.stderr.read()
        files = sum(path.stat().st_size for path in Path(directory).rglob("*")
                    if path.is_file())
        print(json.dumps({
            "scope": "write-only local A/B, not official",
            "rows": args.rows,
            "write_seconds": write_seconds,
            "data_file_bytes": files,
            "peak_process_rss_kib": peak_rss,
        }, indent=2))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
