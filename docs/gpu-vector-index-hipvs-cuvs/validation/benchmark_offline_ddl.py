#!/usr/bin/env python3
"""Reproducible offline-DDL CPU/hipVS comparison; never benchmarks batch_knn.

Requires Python 3, numpy and pymysql. Uses a new database name supplied by the
caller, identical float32 inputs, held-out queries and brute-force ground truth.
The script fails on SQL errors, incomplete results, or missing vector index plans.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time

import numpy as np
import pymysql


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def vector(v):
    # Nine significant decimal digits round-trip float32; ground truth uses
    # exactly these values, not higher precision inputs lost at SQL import.
    return "[" + ",".join(format(float(x), ".9g") for x in v) + "]"


def prepare(root, n, dim, nq, seed):
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    config = dict(n=n, dim=dim, nq=nq, seed=seed, distribution="independent_normal_unit_f32")
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved["config"] != config:
            raise ValueError("Cached dataset has different parameters")
        for name, expected in saved["sha256"].items():
            if digest(root / name) != expected:
                raise ValueError("Cached dataset checksum mismatch: " + name)
        return saved
    rng = np.random.default_rng(seed)
    base = rng.standard_normal((n, dim), dtype=np.float32)
    base /= np.linalg.norm(base, axis=1, keepdims=True)
    queries = rng.standard_normal((nq, dim), dtype=np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    np.save(root / "base.npy", base)
    np.save(root / "queries.npy", queries)
    with (root / "base.tsv").open("w") as out:
        for i, row in enumerate(base):
            out.write(f"{i}\t{vector(row)}\n")
    # Chunked exact L2 reference; float64 avoids cancellation/rounding at top-k.
    # O(n*nq) reference is outside all reported import/build/query timings.
    best_d = np.full((nq, 100), np.inf)
    best_i = np.full((nq, 100), -1, dtype=np.int64)
    q64 = queries.astype(np.float64)
    qnorm = (q64 * q64).sum(axis=1)[:, None]
    for start in range(0, n, 16384):
        b = base[start:start + 16384].astype(np.float64)
        d = qnorm + (b * b).sum(axis=1)[None, :] - 2 * (q64 @ b.T)
        chunk_k = min(100, b.shape[0])
        idx = np.argpartition(d, chunk_k - 1, axis=1)[:, :chunk_k]
        ds = np.take_along_axis(d, idx, axis=1)
        merged_d = np.concatenate([best_d, ds], axis=1)
        merged_i = np.concatenate([best_i, idx + start], axis=1)
        keep = np.argsort(merged_d, axis=1, kind="stable")[:, :100]
        best_d = np.take_along_axis(merged_d, keep, axis=1)
        best_i = np.take_along_axis(merged_i, keep, axis=1)
    np.save(root / "truth.npy", best_i)
    saved = {"config": config, "sha256": {p: digest(root / p) for p in
             ["base.npy", "queries.npy", "truth.npy", "base.tsv"]}}
    manifest.write_text(json.dumps(saved, indent=2) + "\n")
    return saved


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2881)
    ap.add_argument("--rows", type=int, default=100000)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261029)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--backends", nargs="+", choices=["cuvs", "vsag"], default=["vsag", "cuvs"])
    ap.add_argument("--ef-search", type=int, default=1000)
    ap.add_argument("--label", default="unspecified")
    ap.add_argument("--observer-bin", type=Path)
    ap.add_argument("--bridge-lib", type=Path)
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    if not args.database.startswith("amd_bench_") or not args.database.replace("_", "").isalnum():
        ap.error("Use a new database name beginning amd_bench_ (letters/digits/underscores)")
    if args.rows < 100 or args.queries < 1 or args.repeats < 1:
        ap.error("rows >= 100, queries >= 1 and repeats >= 1 required")
    dataset = prepare(args.data_dir.resolve(), args.rows, args.dim, args.queries, args.seed)
    if args.prepare_only:
        print(json.dumps(dataset, indent=2)); return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("Output already exists; use a new run directory")
    conn = pymysql.connect(host=args.host, port=args.port, user="root", autocommit=True,
                           local_infile=True, read_timeout=7200, write_timeout=7200)
    cur = conn.cursor()
    cur.execute("SET ob_query_timeout=7200000000")
    cur.execute("SET ob_trx_timeout=7200000000")
    # Runtime search uses the session variable, not just the index DDL option.
    # Omitting this silently measures VSAG at the server default (usually 64).
    cur.execute("SET ob_hnsw_ef_search=%s", (args.ef_search,))
    cur.execute("SELECT @@session.ob_hnsw_ef_search")
    actual_ef_search = int(cur.fetchone()[0])
    if actual_ef_search != args.ef_search:
        raise RuntimeError("Session ef_search differs from benchmark setting")
    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]
    cur.execute("CREATE DATABASE `" + args.database + "`")
    cur.execute("USE `" + args.database + "`")
    report = {"label": args.label, "version": version, "dataset": dataset, "ef_search": actual_ef_search,
              "m": 16, "ef_construction": 200, "runs": [],
              "artifacts": {name: digest(path) for name, path in
                            [("observer_sha256", args.observer_bin), ("bridge_sha256", args.bridge_lib)] if path},
              "timing": "CREATE VECTOR INDEX wall time; first query reported separately",
              "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                          "cpu_count_visible": os.cpu_count()}}
    queries = np.load(args.data_dir / "queries.npy")
    truth = np.load(args.data_dir / "truth.npy")

    def save():
        tmp = args.output.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2) + "\n")
        tmp.replace(args.output)

    save()
    try:
        for repeat in range(args.repeats):
            # Alternate order to reduce drift from warming/thermal conditions.
            order = args.backends if repeat % 2 == 0 else args.backends[::-1]
            for backend in order:
                table = f"items_{backend}_{repeat}"
                cur.execute(f"CREATE TABLE {table}(id BIGINT PRIMARY KEY, v VECTOR({args.dim}))")
                t = time.perf_counter()
                cur.execute(f"LOAD DATA LOCAL INFILE %s INTO TABLE {table} FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' (id,v)",
                            (str((args.data_dir / "base.tsv").resolve()),))
                load_s = time.perf_counter() - t
                cur.execute("SHOW WARNINGS")
                warnings = cur.fetchall()
                if warnings:
                    raise RuntimeError(f"Import warnings: {warnings[:5]}")
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                if cur.fetchone()[0] != args.rows:
                    raise RuntimeError("Imported row count mismatch")
                # Cross-check the independent NumPy truth against SQL exact
                # search before the index exists; this is outside build timing.
                if repeat == 0:
                    for qi in range(min(3, args.queries)):
                        cur.execute(f"SELECT id FROM {table} ORDER BY l2_distance(v,%s) LIMIT 10",
                                    (vector(queries[qi]),))
                        if {int(row[0]) for row in cur.fetchall()} != set(truth[qi, :10]):
                            raise RuntimeError("SQL exact result differs from generated ground truth")
                t = time.perf_counter()
                cur.execute(f"CREATE VECTOR INDEX idx ON {table}(v) WITH "
                            f"(distance=l2,type=hnsw,lib={backend},m=16,ef_construction=200,ef_search={args.ef_search})")
                build_s = time.perf_counter() - t
                statement = f"SELECT id FROM {table} ORDER BY l2_distance(v,%s) APPROXIMATE LIMIT 10"
                t = time.perf_counter()
                cur.execute(statement, (vector(queries[0]),))
                first = cur.fetchall()
                first_s = time.perf_counter() - t
                if len(first) != 10:
                    raise RuntimeError("First query did not return ten rows")
                cur.execute("EXPLAIN " + statement, (vector(queries[0]),))
                plan = "\n".join(str(x) for row in cur.fetchall() for x in row)
                if "VECTOR" not in plan.upper():
                    raise RuntimeError("Query plan does not use a vector operator: " + plan)
                ids, times, recalls = [], [], []
                for qi, query in enumerate(queries):
                    t = time.perf_counter()
                    cur.execute(statement, (vector(query),))
                    got = [int(row[0]) for row in cur.fetchall()]
                    times.append(time.perf_counter() - t)
                    if len(got) != 10 or len(set(got)) != 10 or any(i < 0 or i >= args.rows for i in got):
                        raise RuntimeError("Invalid/incomplete ANN result")
                    ids.append(got)
                    recalls.append(len(set(got).intersection(truth[qi, :10])) / 10)
                run = dict(backend=backend, repeat=repeat, import_s=load_s, build_s=build_s,
                           first_query_s=first_s, ready_s=build_s + first_s,
                           recall_at_10=statistics.mean(recalls), query_median_s=statistics.median(times),
                           query_p95_s=float(np.percentile(times, 95)),
                           query_seconds=times, recall_by_query=recalls, neighbors=ids, plan=plan)
                report["runs"].append(run)
                save()
                print(json.dumps({k: v for k, v in run.items() if k not in
                                  ["query_seconds", "recall_by_query", "neighbors", "plan"]}), flush=True)
                # Drop only the table created by this run, after saving results.
                # Prevent prior runs' GPU indexes/memory from biasing later ones.
                cur.execute(f"DROP TABLE {table}")
        report["complete"] = True
        save()
    except Exception as exc:
        report["complete"] = False
        report["error"] = str(exc)
        save()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
