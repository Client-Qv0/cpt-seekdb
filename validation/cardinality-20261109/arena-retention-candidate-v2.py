#!/usr/bin/env python3
"""One bounded B/C arena-retention diagnostic, not a performance comparison."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
spec = importlib.util.spec_from_file_location("frozen_probe_v2", HERE / "probe-v2.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def run(version):
    binary = ROOT / "build-cardinality" / version / "release/minivectordb"
    directory = Path(tempfile.mkdtemp(prefix=f"mvdb-arena-{version}-", dir="/var/tmp"))
    case = {"version": version, "committed_rows": 10000, "temporary_rows": 250000,
            "batch_rows": 1000, "schema": "id BIGINT PRIMARY KEY, x BIGINT",
            "seed": None, "id_order": "ascending", "cache": "no scan; only PK equality probes",
            "binary_sha256": probe.sha256(binary), "containers": [], "phases": [],
            "passed": False, "data_directory": str(directory)}
    started = time.monotonic()
    deadline = started + 180
    db = None
    phase_deadline = deadline

    def open_db(label):
        nonlocal db
        db = probe.ContainerDatabase(binary, directory, label=label)
        case["containers"].append(db.record)

    def query(sql):
        remaining = min(deadline, phase_deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Bounded arena diagnostic deadline exceeded")
        return db.query(sql, timeout=remaining)

    def phase(label, fn):
        nonlocal phase_deadline
        phase_deadline = min(deadline, time.monotonic() + 60)
        rec = {"name": label, "before": probe.compact(db.capture(label + ":before")) if db else None}
        case["phases"].append(rec)
        begin = time.monotonic()
        try:
            rec["detail"] = fn()
            rec["passed"] = True
        finally:
            rec["seconds"] = time.monotonic() - begin
            rec["after"] = probe.compact(db.capture(label + ":after")) if db else None
            rec["settled_samples"] = []
            if db and rec.get("passed"):
                settle_started = time.monotonic()
                for i in range(3):
                    time.sleep(.5)
                    rec["settled_samples"].append(probe.compact(db.capture(f"{label}:settled_{i + 1}")))
                rec["settling_seconds_excluded_from_stage_time"] = time.monotonic() - settle_started
            print(json.dumps({"version": version, "phase": label, "seconds": rec["seconds"],
                              "passed": rec.get("passed", False), "memory": rec["after"],
                              "settled": rec["settled_samples"][-1] if rec["settled_samples"] else None}), flush=True)

    def insert(first, count):
        for key in range(first, first + count, 1000):
            query("INSERT INTO items VALUES " + ",".join(f"({i},{i % 97})" for i in range(key, min(key + 1000, first + count))) + ";")
        return {"acknowledged_rows": count}

    def verify_clean():
        for key in (0, 9999):
            if probe.rows(query(f"SELECT id,x FROM items WHERE id={key};")) != [[key, key % 97]]:
                raise AssertionError("Committed data changed")
        for key in (10000, 259999):
            if probe.rows(query(f"SELECT id FROM items WHERE id={key};")):
                raise AssertionError("Uncommitted row survived")
        return {"committed_boundary_rows": 2, "absent_uncommitted_boundary_rows": 2}

    def begin_pending():
        query("BEGIN;")
        insert(10000, 250000)
        for key in (10000, 259999):
            if probe.rows(query(f"SELECT id FROM items WHERE id={key};")) != [[key]]:
                raise AssertionError("Pending data missing")
        return {"pending_rows": 250000}

    try:
        open_db("arena committed setup")
        phase("create", lambda: query("CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT);"))
        phase("committed_10k", lambda: insert(0, 10000))
        phase("first_pending_250k", begin_pending)
        phase("first_rollback", lambda: (query("ROLLBACK;"), verify_clean()))
        phase("second_pending_250k_reuse", begin_pending)
        phase("second_rollback", lambda: (query("ROLLBACK;"), verify_clean()))
        db.close()
        db = None
        def clean_restart():
            open_db("restart after two rollbacks")
            return verify_clean()
        phase("restart_after_rollbacks", clean_restart)
        phase("third_pending_250k_before_kill", begin_pending)
        db.close(kill=True)
        db = None
        def tail_recovery():
            open_db("recover discarded uncommitted 250k tail")
            return verify_clean()
        phase("recover_uncommitted_tail", tail_recovery)
        case["passed"] = True
    except BaseException as error:
        case["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        if db:
            db.close(kill=not case["passed"])
        case["seconds"] = time.monotonic() - started
        if case["passed"]:
            shutil.rmtree(directory)
            case["data_cleaned"] = True
    return case


result = {"driver_sha256": probe.sha256(__file__), "adapter_sha256": probe.sha256(HERE / "probe-v2.py"),
          "limits": {"memory_max": 134217728, "swap_max": 0, "cpu_max": "200000 100000",
                     "stage_seconds": 60, "per_version_seconds": 180},
          "official_benchmark": False, "cases": [],
          "interpretation": ["Single B/C resource diagnostic, not paired speed evidence.",
                             "Rollback object reclamation does not imply immediate allocator-page release.",
                             "Check anon/file/current and restart, not only cumulative peak.",
                             "Recovery checks boundary records; it is not a full row-by-row data oracle."]}
pid = None
try:
    pid = probe.start_daemon()
    for version in ("baseline", "candidate-v2"):
        result["cases"].append(run(version))
        (HERE / "arena-retention-candidate-v2-results.json").write_text(json.dumps(result, indent=2) + "\n")
finally:
    result["daemon_cleanup"] = probe.stop_daemon(pid)
    (HERE / "arena-retention-candidate-v2-results.json").write_text(json.dumps(result, indent=2) + "\n")
print("ARENA_RESULT", json.dumps([{k: c.get(k) for k in ("version", "passed", "seconds", "error")} for c in result["cases"]]), flush=True)
