#!/usr/bin/env python3
"""Isolated GPU offline-DDL/restart/DML smoke without Docker (TRACE build)."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import numpy as np
import pymysql

from benchmark_offline_ddl import vector


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--observer", type=Path, required=True)
    ap.add_argument("--bridge-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--port", type=int, default=2991)
    args = ap.parse_args()
    root = args.run_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    base_dir = root / "server"
    base_dir.mkdir()
    trace = root / "trace.log"
    state = {"cases": {}, "complete": False}
    process = None
    conn = None
    probe = vector(np.load(args.data_dir / "base.npy", mmap_mode="r")[0])
    dim = np.load(args.data_dir / "base.npy", mmap_mode="r").shape[1]
    with (args.data_dir / "base.tsv").open() as src, (root / "base.tsv").open("w") as dst:
        for _ in range(10000):
            line = src.readline()
            if not line:
                raise ValueError("At least 10000 input rows required")
            dst.write(line)

    def stop():
        nonlocal process, conn
        if conn is not None:
            conn.close()
            conn = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError("Observer did not terminate gracefully")

    def start():
        nonlocal process, conn
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", args.port)) == 0:
                raise RuntimeError("Port already in use; refusing to touch its server")
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = f"{args.bridge_dir.resolve()}:/opt/hipvs/lib:/opt/rocm/lib"
        env["OB_VSAG_TRACE"] = "1"
        env["OB_VSAG_TRACE_FILE"] = str(trace)
        with (root / "observer.log").open("ab") as out:
            process = subprocess.Popen([
                str(args.observer.resolve()), "--nodaemon", f"--port={args.port}",
                f"--base-dir={base_dir}", "--log-level=INFO",
                "--parameter", "cpu_count=4", "--parameter", "memory_budget=8G",
                "--parameter", "datafile_size=2G", "--parameter", "datafile_maxsize=6G",
                "--parameter", "log_disk_size=2G"], cwd=base_dir, env=env,
                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        for _ in range(90):
            if process.poll() is not None:
                raise RuntimeError("Observer exited during startup")
            try:
                conn = pymysql.connect(host="127.0.0.1", port=args.port, user="root",
                                       autocommit=True, local_infile=True, connect_timeout=1,
                                       read_timeout=300)
                sql("SELECT 1")
                sql("SET ob_query_timeout=300000000")
                sql("SET ob_hnsw_ef_search=1000")
                with conn.cursor(pymysql.cursors.DictCursor) as cur:
                    cur.execute("SHOW PARAMETERS LIKE 'memory_budget'")
                    state["memory_budget_read_back"] = [row["value"] for row in cur.fetchall()]
                return
            except pymysql.MySQLError:
                if conn is not None:
                    conn.close()
                    conn = None
                time.sleep(2)
        raise RuntimeError("Observer startup timeout")

    def sql(statement, params=None):
        with conn.cursor() as cur:
            cur.execute(statement, params)
            return cur.fetchall()

    def query(table="items", where="", exact=False):
        approx = "" if exact else "APPROXIMATE"
        return [int(row[0]) for row in sql(
            f"SELECT id FROM amd_lifecycle.{table} {where} ORDER BY l2_distance(v,%s) {approx} LIMIT 10",
            (probe,))]

    def trace_tail(offset):
        with trace.open("rb") as f:
            f.seek(offset)
            return f.read().decode()

    try:
        start()
        sql("ALTER SYSTEM SET ob_vector_memory_limit_percentage=50")
        sql("CREATE DATABASE amd_lifecycle")
        sql("USE amd_lifecycle")
        for table, backend in [("items", "cuvs"), ("cpu_items", "vsag")]:
            sql(f"CREATE TABLE {table}(id BIGINT PRIMARY KEY,v VECTOR({dim}))")
            sql(f"LOAD DATA LOCAL INFILE %s INTO TABLE {table} FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' (id,v)", (str(root / "base.tsv"),))
            assert sql(f"SELECT COUNT(*) FROM {table}")[0][0] == 10000
            sql(f"CREATE VECTOR INDEX idx ON {table}(v) WITH (distance=l2,type=hnsw,lib={backend},m=16,ef_construction=200)")
        first = query()
        assert len(set(first)) == 10 and first[0] == 0
        assert set(first) == set(query(exact=True))
        assert "cuvs_serve" in trace.read_text()
        state["cases"]["offline_ddl_gpu_query"] = "PASS"
        stop()
        offset = trace.stat().st_size
        start()
        reloaded = query()
        tail = trace_tail(offset)
        assert reloaded == first
        assert "fdeserialize" in tail and "cuvs_serve" in tail and "cuvs_build" not in tail
        state["cases"]["restart_gpu_without_rebuild"] = "PASS"
        offset = trace.stat().st_size
        assert set(query("cpu_items")) == set(query("cpu_items", exact=True))
        assert "cuvs_" not in trace_tail(offset)
        state["cases"]["cpu_isolation_after_restart"] = "PASS"
        assert set(query(where="WHERE id>=9000")) == set(query(where="WHERE id>=9000", exact=True))
        state["cases"]["filter_fallback"] = "PASS"
        sql("DELETE FROM amd_lifecycle.items WHERE id=0")
        deleted = query()
        assert 0 not in deleted and set(deleted) == set(query(exact=True))
        state["cases"]["delete_visibility"] = "PASS"
        sql("INSERT INTO amd_lifecycle.items VALUES(9000000000,%s)", (probe,))
        inserted = query()
        assert inserted[0] == 9000000000 and set(inserted) == set(query(exact=True))
        state["cases"]["incremental_insert_visibility"] = "PASS"
        state["complete"] = True
    except Exception as exc:
        state["error"] = repr(exc)
        raise
    finally:
        try:
            stop()
        except Exception as exc:
            state["complete"] = False
            state["cleanup_error"] = repr(exc)
            raise
        finally:
            (root / "summary.json").write_text(json.dumps(state, indent=2) + "\n")
            print(json.dumps(state, indent=2), flush=True)


if __name__ == "__main__":
    main()
