#!/usr/bin/env python3
"""Paired local baseline/candidate evidence with actual cgroup limits.

The canonical SQL comes from a frozen audit oracle and is compared byte-for-byte
with a dry-run capture of the frozen benchmark script. Actual database runs use
cardinality_probe.ContainerDatabase; all oracle computation and correctness
checking occurs outside the database cgroup and outside every timed interval.

This is not the official baseline, performance score, or submission driver.
No workload execution happens with --prepare-only. Do not run while another
agent is conducting resource diagnostics or performance measurements.
"""

import argparse
import datetime
import gzip
import hashlib
import heapq
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import time


MEMORY_BYTES = 128 * 1024 * 1024
CPU_QUOTA = 200000
CPU_PERIOD = 100000
WARMUP_QUERIES = 10
PAIR_ORDERS = (("baseline", "candidate"), ("candidate", "baseline"), ("baseline", "candidate"))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_source(source, manifest_path):
    source, manifest_path = Path(source).resolve(), Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    verified = []
    for entry in manifest["files"]:
        relative = entry["path"]
        path = (source / relative).resolve()
        if not path.is_relative_to(source):
            raise ValueError(f"Manifest path leaves source directory: {relative}")
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ValueError(f"Frozen source hash mismatch: {path}")
        verified.append({"path": relative, "sha256": actual, "bytes": path.stat().st_size})
    return {
        "source_directory": str(source),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_tree_sha256": manifest.get("tree_sha256"),
        "files": verified,
        "all_manifest_files_verified": True,
    }


def identity(binary, source, manifest):
    binary = Path(binary).resolve()
    return {
        "binary_path": str(binary),
        "binary_sha256": sha256_file(binary),
        "binary_bytes": binary.stat().st_size,
        "source": verify_source(source, manifest),
    }


def prepare_oracle(oracle, batches, queries):
    """Compute truth before launching a measured container, never inside it."""
    import numpy as np
    ids, groups, vectors, query_inputs = oracle.parse_oracle_inputs(batches, queries, np)
    truth = []
    for index, (q, group) in enumerate(query_inputs):
        difference = vectors - q
        distances = np.sqrt(np.sum(difference * difference, axis=1, dtype=np.float64))
        eligible = np.arange(len(ids)) if group is None else np.flatnonzero(groups == group)
        selected = eligible[np.lexsort((ids[eligible], distances[eligible]))][:oracle.TOP_K]
        truth.append({
            "query_index": index,
            "group": None if group is None else int(group),
            "rows": [[int(ids[row]), float(distances[row])] for row in selected],
        })
    return truth, {
        "numpy_version": np.__version__,
        "storage_and_query_quantization": "IEEE-754 binary32, then promoted to binary64",
        "distance": "sqrt(sum((stored - query)^2, dtype=float64)); exhaustive eligible-record scan",
        "tie_break": "primary key ascending",
        "absolute_tolerance": oracle.DISTANCE_ATOL,
        "relative_tolerance": oracle.DISTANCE_RTOL,
        "location": "Driver process outside database cgroup; computed before all measured runs",
    }


def check_responses(responses, truth, oracle):
    """Called only after the measured database container has been closed."""
    checks = []
    for item in responses:
        query_index = item["query_index"]
        expected = truth[query_index]
        actual = item["response"]
        wanted_rows = expected["rows"]
        wanted_ids = [row[0] for row in wanted_rows]
        actual_rows = actual.get("rows", []) if isinstance(actual, dict) else []
        issues, ids, errors = [], [], []
        if not isinstance(actual, dict) or actual.get("ok") is not True:
            issues.append("query_response_error")
        if not isinstance(actual_rows, list):
            actual_rows = []
            issues.append("invalid_row_array")
        if len(actual_rows) != len(wanted_rows):
            issues.append("result_count")
        expected_distances = dict(wanted_rows)
        for index, row in enumerate(actual_rows):
            if not isinstance(row, list) or len(row) != 2:
                issues.append(f"row_{index}:shape")
                continue
            key, distance = row
            if not isinstance(key, int) or isinstance(key, bool) or not 0 <= key < oracle.ROWS:
                issues.append(f"row_{index}:id")
                continue
            ids.append(key)
            if expected["group"] is not None and key % 5 != expected["group"]:
                issues.append(f"row_{index}:filter")
            if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance):
                issues.append(f"row_{index}:distance_type")
                continue
            if key in expected_distances:
                correct = expected_distances[key]
                error = abs(float(distance) - correct)
                errors.append(error)
                if error > oracle.DISTANCE_ATOL + oracle.DISTANCE_RTOL * abs(correct):
                    issues.append(f"row_{index}:distance")
            else:
                # Wrong membership is already a failure; do not certify its
                # distance using another member's expected distance.
                issues.append(f"row_{index}:not_in_true_topk")
        if len(set(ids)) != len(ids):
            issues.append("duplicate_ids")
        if set(ids) != set(wanted_ids):
            issues.append("topk_membership")
        if ids != wanted_ids:
            issues.append("topk_order")
        checks.append({
            "phase": item["phase"],
            "query_index": query_index,
            "filter_group": expected["group"],
            "query_sha256": item["query_sha256"],
            "passed": not issues,
            "issues": issues,
            "expected_rows": wanted_rows,
            "returned_rows": actual_rows,
            "recall_at_10": len(set(ids).intersection(wanted_ids)) / len(wanted_ids),
            "maximum_absolute_distance_error": max(errors) if errors else None,
        })
    summary = {}
    for filtered in (False, True):
        subset = [entry for entry in checks if entry["phase"] == "warm_queries" and (entry["filter_group"] is not None) == filtered]
        recalls = [entry["recall_at_10"] for entry in subset]
        summary["filtered" if filtered else "unfiltered"] = {
            "queries": len(subset),
            "minimum_recall_at_10": min(recalls) if recalls else None,
            "mean_recall_at_10": statistics.mean(recalls) if recalls else None,
        }
    return checks, summary


def snapshot(client, label, output):
    result = client.capture(label)
    output.append({"label": label, "snapshot": result})
    return result


def validate_runtime_snapshot(value, cpuset=None):
    """Read kernel limit files from a raw capture, not requested Docker flags.

    The adapter may place its raw files under a nested dictionary. Require all
    three actual limit-file values; absence is not interpreted as compliance.
    """
    found = {}

    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                basename = str(key).split("/")[-1]
                if basename in {"memory.max", "memory.swap.max", "cpu.max", "cpuset.cpus.effective"}:
                    if isinstance(child, (str, int)):
                        found[basename] = str(child).strip()
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    required = {"memory.max": str(MEMORY_BYTES), "memory.swap.max": "0", "cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}"}
    if any(found.get(key) != expected for key, expected in required.items()):
        raise RuntimeError(f"Actual cgroup limits are absent or differ: found={found}, required={required}")
    if cpuset is not None:
        def cpu_ids(text):
            output = set()
            for value in text.split(","):
                bounds = [int(part) for part in value.split("-")]
                output.update(range(bounds[0], bounds[-1] + 1))
            return output
        if not found.get("cpuset.cpus.effective") or cpu_ids(found["cpuset.cpus.effective"]) != cpu_ids(cpuset):
            raise RuntimeError(f"Effective CPU affinity differs: {found.get('cpuset.cpus.effective')} vs {cpuset}")
    return found


def integer_fields(text):
    result = {}
    for line in str(text or "").splitlines():
        fields = line.split()
        if len(fields) == 2:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                pass
    return result


def resources(record):
    """Summarize retained kernel samples without claiming RSS is cgroup usage."""
    samples = list(record.get("samples", []))
    samples += [entry["values"] for entry in record.get("snapshots", []) if entry.get("values")]
    if record.get("last_live_snapshot"):
        samples.append(record["last_live_snapshot"])
    samples.sort(key=lambda sample: sample.get("monotonic", 0))
    peaks = {"memory_current_bytes": [], "memory_peak_bytes": [], "anon_bytes": [], "file_bytes": []}
    events = {}
    for sample in samples:
        stat = integer_fields(sample.get("memory.stat"))
        for key, value in (("memory_current_bytes", sample.get("memory.current")),
                           ("memory_peak_bytes", sample.get("memory.peak")),
                           ("anon_bytes", stat.get("anon")), ("file_bytes", stat.get("file"))):
            if value is not None:
                peaks[key].append(int(value))
        for key, value in integer_fields(sample.get("memory.events")).items():
            events[key] = max(events.get(key, 0), value)
    state = record.get("docker_final_state", {})
    expected_exit = 137 if record.get("requested_kill") else 0
    healthy = (bool(samples) and bool(state) and not state.get("OOMKilled", False)
               and state.get("ExitCode") == expected_exit and not state.get("Error")
               and not record.get("cleanup_timeout")
               and events.get("oom", 0) == 0 and events.get("oom_kill", 0) == 0)
    return {
        "samples_retained": len(samples),
        "maxima": {key: max(values) if values else None for key, values in peaks.items()},
        "memory_events_maximum_counters": events,
        "first_live_memory_pressure": samples[0].get("memory.pressure") if samples else None,
        "last_live_memory_pressure": samples[-1].get("memory.pressure") if samples else None,
        "first_live_io_stat": samples[0].get("io.stat") if samples else None,
        "last_live_io_stat": samples[-1].get("io.stat") if samples else None,
        "docker_final_state": state,
        "expected_exit_code": expected_exit,
        "healthy": healthy,
        "limitations": "Raw io.stat is retained without physical attribution or a final writeback sync. Independent anon/file sampled maxima need not occur at the same instant. memory.peak reaching the cap alone is not an OOM verdict.",
    }


def run_one(adapter, label, variant, variant_identity, path, batches, queries, truth, oracle, image, socket, cpuset):
    path.mkdir(parents=True, exist_ok=False)
    data_dir = path / "data"
    data_dir.mkdir()
    report = {
        "run_label": label,
        "variant": variant,
        "identity": variant_identity,
        "timings": {},
        "snapshots": [],
        "response_consumer": "Same ContainerDatabase.query JSON consumer; output recording only during timed phases; oracle, checks, file writes outside timing",
        "cache_note": "Process-first query after writes is not an OS-cold-cache measurement. No global drop_caches is issued.",
        "failure": None,
    }
    responses, write_responses = [], []
    query_hashes = [oracle.statement_sha256(query) for query in queries]
    client = None
    try:
        start = time.perf_counter()
        client = adapter.ContainerDatabase(Path(variant_identity["binary_path"]), data_dir, image=image, socket=socket, label=label, cpuset=cpuset)
        report["timings"]["initial_container_launch_seconds"] = time.perf_counter() - start
        first_capture = snapshot(client, "container_started", report["snapshots"])
        report["verified_runtime_limits"] = validate_runtime_snapshot(first_capture, cpuset)
        client.query(oracle.CREATE_SQL, timeout=120)
        snapshot(client, "before_write", report["snapshots"])
        start = time.perf_counter()
        for statement in batches:
            write_responses.append(client.query(statement, timeout=120))
        report["timings"]["write_batches_seconds"] = time.perf_counter() - start
        snapshot(client, "after_write", report["snapshots"])

        start = time.perf_counter()
        result = client.query(queries[0], timeout=120)
        report["timings"]["process_first_query_seconds"] = time.perf_counter() - start
        responses.append({"phase": "process_first_query", "query_index": 0, "query_sha256": query_hashes[0], "response": result})
        snapshot(client, "after_process_first_query", report["snapshots"])

        # Exactly the same extra warm-up sequence is used for both variants.
        start = time.perf_counter()
        for index, statement in enumerate(queries[:WARMUP_QUERIES]):
            result = client.query(statement, timeout=120)
            responses.append({"phase": "fixed_warmup", "query_index": index, "query_sha256": query_hashes[index], "response": result})
        report["timings"]["fixed_warmup_seconds_not_in_warm_query_time"] = time.perf_counter() - start
        snapshot(client, "after_fixed_warmup", report["snapshots"])

        start = time.perf_counter()
        for index, statement in enumerate(queries):
            result = client.query(statement, timeout=120)
            responses.append({"phase": "warm_queries", "query_index": index, "query_sha256": query_hashes[index], "response": result})
        report["timings"]["warm_queries_seconds"] = time.perf_counter() - start
        snapshot(client, "after_warm_queries", report["snapshots"])
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
    finally:
        if client is not None:
            try:
                client.close(kill=report["failure"] is not None, timeout=20)
            except Exception as error:
                report["close_failure"] = f"{type(error).__name__}: {error}"
            report["container_record"] = client.record

    # Reopen the same directory under the same limits; the new container has a
    # fresh process but OS page cache is not deliberately made cold.
    if report["failure"] is None:
        client = None
        recovery = {"snapshots": []}
        report["recovery"] = recovery
        probe = f"SELECT id,grp FROM bench WHERE id={oracle.ROWS - 1};"
        try:
            start = time.perf_counter()
            client = adapter.ContainerDatabase(Path(variant_identity["binary_path"]), data_dir, image=image, socket=socket, label=label + "-restart", cpuset=cpuset)
            result = client.query(probe, timeout=120)
            report["timings"]["restart_startup_to_first_response_seconds"] = time.perf_counter() - start
            recovery["timing_includes"] = "Docker container launch + database startup/replay + primary-key probe + response consumption; not isolated WAL recovery time"
            recovery["response"] = result
            recovery["probe_sql"] = probe
            recovery["probe_sql_sha256"] = oracle.statement_sha256(probe)
            captured = snapshot(client, "restart_first_response", recovery["snapshots"])
            recovery["verified_runtime_limits"] = validate_runtime_snapshot(captured, cpuset)
        except Exception as error:
            report["failure"] = f"restart {type(error).__name__}: {error}"
        finally:
            if client is not None:
                try:
                    client.close(kill=report["failure"] is not None, timeout=20)
                except Exception as error:
                    recovery["close_failure"] = f"{type(error).__name__}: {error}"
                recovery["container_record"] = client.record

    # Neither a live measured database nor its cgroup is charged for the oracle.
    checks, recall = check_responses(responses, truth, oracle)
    report["correctness"] = {
        "expected_result_sets": 1 + WARMUP_QUERIES + len(queries),
        "checked_result_sets": len(checks),
        "result_sets_passed": sum(check["passed"] for check in checks),
        "result_sets_failed": sum(not check["passed"] for check in checks),
        "warm_query_recall": recall,
        "write_batches_acknowledged": len(write_responses),
        "all_write_batch_counts_correct": len(write_responses) == len(batches) and all(value.get("affected") == oracle.BATCH_SIZE for value in write_responses),
    }
    if "recovery" in report and "response" in report["recovery"]:
        answer = report["recovery"]["response"]
        expected = [[oracle.ROWS - 1, f"g{(oracle.ROWS - 1) % 5}"]]
        report["correctness"]["restart_probe_correct"] = answer.get("ok") is True and answer.get("rows") == expected
    else:
        report["correctness"]["restart_probe_correct"] = False
    after_hash = sha256_file(variant_identity["binary_path"])
    report["binary_sha256_after"] = after_hash
    report["binary_unchanged"] = after_hash == variant_identity["binary_sha256"]
    report["resources"] = {
        "main": resources(report.get("container_record", {})),
        "restart": resources(report.get("recovery", {}).get("container_record", {})),
    }
    report["passed"] = (
        report["failure"] is None and "close_failure" not in report
        and "close_failure" not in report.get("recovery", {})
        and report["binary_unchanged"]
        and len(checks) == 1 + WARMUP_QUERIES + len(queries)
        and all(check["passed"] for check in checks)
        and report["correctness"]["all_write_batch_counts_correct"]
        and report["correctness"]["restart_probe_correct"]
        and all(record["healthy"] for record in report["resources"].values())
    )
    write_json(path / "responses.json", {"writes": write_responses, "queries": responses})
    write_json(path / "oracle-checks.json", checks)
    write_json(path / "run.json", report)
    return report


def prepare_cardinality_workload(kind, count, batch_rows, transaction_rows):
    """Fixed short-record input and independent expectations, outside DB timing."""
    if kind not in ("scalar", "vector4") or count < 1000:
        raise ValueError("Cardinality cases need scalar/vector4 and at least 1000 rows")
    def row_sql(key):
        fields = f"{key},{key % 97}"
        if kind == "vector4":
            fields += f",'[{key % 31},{key % 17},{key % 7},{key % 3}]'"
        return "(" + fields + ")"

    stages = []
    def command(sql, expected_rows=None, affected=None, id_column=None):
        entry = {"sql": sql, "sha256": hashlib.sha256(sql.encode()).hexdigest()}
        if expected_rows is not None:
            entry["expected_rows"] = expected_rows
        if affected is not None:
            entry["affected"] = affected
        if id_column is not None:
            entry["id_column"] = id_column
        return entry

    extra = ",v VECTOR(4)" if kind == "vector4" else ""
    stages.append(("create", [command(f"CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT{extra});")]))
    writes = []
    for first in range(0, count, batch_rows):
        end = min(count, first + batch_rows)
        writes.append(command("INSERT INTO items VALUES " + ",".join(row_sql(key) for key in range(first, end)) + ";", affected=end - first))
    stages.append(("write_batches", writes))
    keys = sorted({0, count - 1, count // 2, *[i * (count - 1) // 31 for i in range(32)]})
    point_queries = [command(f"SELECT id,x FROM items WHERE id={key};", [[key, key % 97]], id_column=0) for key in keys]
    stages.append(("process_first_pk_query", point_queries[:1]))
    stages.append(("pk_lookup_remaining", point_queries[1:]))
    scan = command("SELECT id,x FROM items WHERE x>=0 ORDER BY x DESC,id ASC LIMIT 8;",
                   [[96 + i * 97, 96] for i in range(8)], id_column=0)
    stages.append(("scan_first_after_pk", [scan]))
    stages.append(("scan_warm_three", [scan] * 3))
    if kind == "vector4":
        # Exhaustive FP64 reference over the actual deterministic integer-valued
        # FP32 input. Tuple ordering independently implements distance, then PK.
        top = heapq.nsmallest(8, ((math.sqrt((key % 31 - .5) ** 2 + (key % 17 - 1.5) ** 2
                                            + (key % 7 - 2.5) ** 2 + (key % 3 - 1.) ** 2), key)
                                for key in range(count) if key % 97 >= 47))
        vector = command("SELECT id,L2_DISTANCE(v,'[0.5,1.5,2.5,1]') AS d FROM items WHERE x>=47 ORDER BY d,id LIMIT 8;",
                         [[key, distance] for distance, key in top], id_column=0)
        vector["filter_description"] = "x>=47, where x=id%97"
        stages.append(("vector_topk_first", [vector]))
        stages.append(("vector_topk_warm_three", [vector] * 3))
    stages.append(("update_cache_invalidation", [
        command("UPDATE items SET x=999 WHERE id=0;", affected=1),
        command("SELECT x FROM items WHERE id=0;", [[999]]),
    ]))
    stages.append(("restore_update", [command("UPDATE items SET x=0 WHERE id=0;", affected=1)]))
    stages.append(("scan_after_invalidation", [scan]))
    stages.append(("delete_restore", [
        command("DELETE FROM items WHERE id<100;", affected=100),
        command("SELECT id FROM items WHERE id<100 LIMIT 1;", [], id_column=0),
        command("INSERT INTO items VALUES " + ",".join(row_sql(key) for key in range(100)) + ";", affected=100),
    ]))
    pending = min(count, transaction_rows)
    stages.append(("transaction_pending", [
        command("BEGIN;"), command(f"UPDATE items SET x=777 WHERE id<{pending};", affected=pending),
        command("SELECT x FROM items WHERE id=0;", [[777]]),
    ]))
    stages.append(("transaction_rollback_commit_restore", [
        command("ROLLBACK;"), command("SELECT x FROM items WHERE id=0;", [[0]]),
        command("BEGIN;"), command("UPDATE items SET x=666 WHERE id=0;", affected=1),
        command("COMMIT;"), command("SELECT x FROM items WHERE id=0;", [[666]]),
        command("UPDATE items SET x=0 WHERE id=0;", affected=1),
    ]))
    restart = point_queries + [scan]
    all_commands = [entry for _, commands in stages for entry in commands] + restart
    digest = hashlib.sha256()
    for entry in all_commands:
        digest.update((entry["sql"] + "\n").encode())
    return {"kind": kind, "rows": count, "batch_rows": batch_rows,
            "transaction_rows": pending, "stages": stages, "restart": restart,
            "workload_sql_sha256": digest.hexdigest(),
            "generation": {"seed": None, "id": "0..N-1 ascending", "x": "id%97",
                           "vector": "[id%31,id%17,id%7,id%3]" if kind == "vector4" else None}}


def check_cardinality_results(responses):
    """All validation is deferred until after timed containers have stopped."""
    checks = []
    for item in responses:
        entry, actual = item["command"], item["response"]
        issues = []
        if not isinstance(actual, dict) or actual.get("ok") is not True:
            issues.append("response_error")
            actual = {}
        if "affected" in entry and actual.get("affected") != entry["affected"]:
            issues.append("affected_count")
        expected = entry.get("expected_rows")
        returned = actual.get("rows", [])
        maximum_error = 0.0
        recall = None
        if expected is not None:
            if not isinstance(returned, list) or len(returned) != len(expected):
                issues.append("row_count")
            else:
                for row_index, (got_row, want_row) in enumerate(zip(returned, expected)):
                    if not isinstance(got_row, list) or len(got_row) != len(want_row):
                        issues.append(f"row_{row_index}:shape")
                        continue
                    for col, (got, want) in enumerate(zip(got_row, want_row)):
                        if isinstance(want, float):
                            if not isinstance(got, (int, float)) or isinstance(got, bool) or not math.isfinite(got):
                                issues.append(f"row_{row_index}:col_{col}:nonfinite_or_type")
                            else:
                                error = abs(got - want)
                                maximum_error = max(maximum_error, error)
                                if not math.isclose(got, want, rel_tol=1e-12, abs_tol=1e-12):
                                    issues.append(f"row_{row_index}:col_{col}:distance")
                        elif isinstance(got, bool) or got != want:
                            issues.append(f"row_{row_index}:col_{col}:value_or_order")
            if "id_column" in entry and isinstance(returned, list):
                col = entry["id_column"]
                ids = [row[col] for row in returned if isinstance(row, list) and len(row) > col]
                valid_ids = [key for key in ids if isinstance(key, int) and not isinstance(key, bool)]
                wanted = [row[col] for row in expected]
                if len(valid_ids) != len(ids):
                    issues.append("id_type")
                if len(set(valid_ids)) != len(valid_ids):
                    issues.append("duplicate_ids")
                if entry.get("filter_description") and any(key % 97 < 47 for key in valid_ids):
                    issues.append("filter")
                if wanted:
                    recall = len(set(valid_ids).intersection(wanted)) / len(wanted)
        checks.append({"phase": item["phase"], "sql_sha256": entry["sha256"],
                       "passed": not issues, "issues": issues,
                       "expected_rows": expected, "returned_rows": returned,
                       "expected_affected": entry.get("affected"), "returned_affected": actual.get("affected"),
                       "recall": recall, "maximum_absolute_distance_error": maximum_error})
    return checks


def run_cardinality(adapter, label, variant, variant_identity, path, workload, image, socket, cpuset, stage_seconds):
    path.mkdir(parents=True, exist_ok=False)
    data = path / "data"
    data.mkdir()
    report = {"run_label": label, "variant": variant, "identity": variant_identity,
              "kind": workload["kind"], "rows": workload["rows"],
              "workload_sql_sha256": workload["workload_sql_sha256"],
              "timings": {}, "snapshots": [], "failure": None,
              "response_consumer": "Same JSON decoder and list recording for each variant; SQL generation, expected results and correctness comparisons outside timers and database cgroup",
              "cache_note": "First scalar scan follows PK probes; process-first PK query is separate. No OS cache flush. Three warm repetitions are identical for both variants.",
              "restart_note": "SIGKILL after all acknowledged transactions, then Docker launch through first valid PK response. This includes launch, replay and probe; no isolated replay claim."}
    responses = []
    db = None
    try:
        start = time.perf_counter()
        db = adapter.ContainerDatabase(Path(variant_identity["binary_path"]), data, image=image, socket=socket, label=label, cpuset=cpuset)
        report["timings"]["initial_container_launch_seconds"] = time.perf_counter() - start
        validate_runtime_snapshot(snapshot(db, "container_started", report["snapshots"]), cpuset)
        for phase, commands in workload["stages"]:
            snapshot(db, phase + ":before", report["snapshots"])
            started = time.perf_counter()
            try:
                for command in commands:
                    remaining = stage_seconds - (time.perf_counter() - started)
                    if remaining <= 0:
                        raise TimeoutError(f"Phase {phase} exceeded {stage_seconds} seconds")
                    response = db.query(command["sql"], timeout=remaining)
                    responses.append({"phase": phase, "command": command, "response": response})
            finally:
                report["timings"][phase + "_seconds"] = time.perf_counter() - started
                snapshot(db, phase + ":after", report["snapshots"])
    except Exception as error:
        report["failure"] = f"{type(error).__name__}: {error}"
    finally:
        if db is not None:
            try:
                # Deliberate kill is part of the matched crash-recovery scenario.
                db.close(kill=True, timeout=20)
            except Exception as error:
                report["close_failure"] = f"{type(error).__name__}: {error}"
            report["container_record"] = db.record
    if report["failure"] is None and "close_failure" not in report:
        db = None
        try:
            first = workload["restart"][0]
            started = time.perf_counter()
            db = adapter.ContainerDatabase(Path(variant_identity["binary_path"]), data, image=image, socket=socket, label=label + "-restart", cpuset=cpuset)
            response = db.query(first["sql"], timeout=stage_seconds)
            report["timings"]["restart_startup_to_first_response_seconds"] = time.perf_counter() - started
            responses.append({"phase": "restart_first_response", "command": first, "response": response})
            validate_runtime_snapshot(snapshot(db, "restart_first_response", report["snapshots"]), cpuset)
            started = time.perf_counter()
            for command in workload["restart"][1:]:
                remaining = stage_seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    raise TimeoutError("Restart probe sequence exceeded stage budget")
                response = db.query(command["sql"], timeout=remaining)
                responses.append({"phase": "restart_remaining_checks", "command": command, "response": response})
            report["timings"]["restart_remaining_checks_seconds"] = time.perf_counter() - started
            snapshot(db, "restart_checks_finished", report["snapshots"])
        except Exception as error:
            report["failure"] = f"restart {type(error).__name__}: {error}"
        finally:
            if db is not None:
                try:
                    db.close(kill=report["failure"] is not None, timeout=20)
                except Exception as error:
                    report["restart_close_failure"] = f"{type(error).__name__}: {error}"
                report["restart_container_record"] = db.record
    checks = check_cardinality_results(responses)
    expected_count = sum(len(commands) for _, commands in workload["stages"]) + len(workload["restart"])
    report["correctness"] = {"expected_responses": expected_count, "checked_responses": len(checks),
                             "responses_failed": sum(not entry["passed"] for entry in checks),
                             "reference_scope": "All issued responses checked. Every input batch acknowledgement checked. Scalar full-domain TopK and vector filtered exhaustive TopK, fixed PK probes, mutations, rollback/commit and restart probes; not a complete recovered-data dump."}
    report["resources"] = {"main": resources(report.get("container_record", {})),
                           "restart": resources(report.get("restart_container_record", {}))}
    report["binary_sha256_after"] = sha256_file(variant_identity["binary_path"])
    report["binary_unchanged"] = report["binary_sha256_after"] == variant_identity["binary_sha256"]
    report["passed"] = (report["failure"] is None and "close_failure" not in report
                        and "restart_close_failure" not in report and report["binary_unchanged"]
                        and len(checks) == expected_count and all(entry["passed"] for entry in checks)
                        and all(record["healthy"] for record in report["resources"].values()))
    # SQL is archived once per workload. Response records carry statement hashes
    # instead of repeating potentially large INSERT strings for every paired run.
    write_json(path / "responses.json", [{"phase": item["phase"], "sql_sha256": item["command"]["sha256"], "response": item["response"]} for item in responses])
    write_json(path / "oracle-checks.json", checks)
    write_json(path / "run.json", report)
    return report


def distribution(values):
    if not values:
        return {"count": 0}
    average = statistics.mean(values)
    stdev = statistics.pstdev(values)
    return {
        "count": len(values), "values": values,
        "median": statistics.median(values), "minimum": min(values), "maximum": max(values),
        "mean": average, "population_stddev": stdev,
        "coefficient_of_variation": stdev / average if average else None,
    }


def summarize(runs):
    metrics = sorted({metric for run in runs for metric in run["timings"]
                      if metric != "initial_container_launch_seconds"})
    summary = {"variants": {}, "pairs": [], "valid_pairs": 0}
    for variant in ("baseline", "candidate"):
        selected = [run for run in runs if run["variant"] == variant]
        summary["variants"][variant] = {
            "runs": len(selected), "runs_passed": sum(run["passed"] for run in selected),
            "timings": {metric: distribution([run["timings"][metric] for run in selected if metric in run["timings"]]) for metric in metrics},
            "resources": {
                process: {
                    "sampled_and_kernel_maxima": {
                        metric: distribution([run["resources"][process]["maxima"][metric] for run in selected
                                              if run["resources"][process]["maxima"].get(metric) is not None])
                        for metric in ("memory_current_bytes", "memory_peak_bytes", "anon_bytes", "file_bytes")
                    },
                    "unhealthy_runs": sum(not run["resources"][process]["healthy"] for run in selected),
                    "events_by_run": [run["resources"][process]["memory_events_maximum_counters"] for run in selected],
                } for process in ("main", "restart")
            },
        }
    for pair in range(len(PAIR_ORDERS)):
        selected = {run["variant"]: run for run in runs if run["pair_index"] == pair}
        result = {"pair_index": pair, "order": PAIR_ORDERS[pair], "passed": len(selected) == 2 and all(run["passed"] for run in selected.values()), "baseline_over_candidate": {}}
        if result["passed"]:
            summary["valid_pairs"] += 1
            for metric in metrics:
                base, candidate = selected["baseline"]["timings"].get(metric), selected["candidate"]["timings"].get(metric)
                result["baseline_over_candidate"][metric] = base / candidate if base is not None and candidate else None
            result["candidate_over_baseline_resource_maxima"] = {
                process: {
                    metric: (selected["candidate"]["resources"][process]["maxima"][metric]
                             / selected["baseline"]["resources"][process]["maxima"][metric])
                    if selected["baseline"]["resources"][process]["maxima"].get(metric)
                    and selected["candidate"]["resources"][process]["maxima"].get(metric) is not None else None
                    for metric in ("memory_current_bytes", "memory_peak_bytes", "anon_bytes", "file_bytes")
                } for process in ("main", "restart")
            }
        summary["pairs"].append(result)
    summary["paired_ratios"] = {
        metric: distribution([pair["baseline_over_candidate"][metric] for pair in summary["pairs"] if pair["passed"] and pair["baseline_over_candidate"][metric] is not None]) for metric in metrics
    }
    summary["all_six_runs_passed"] = len(runs) == 6 and all(run["passed"] for run in runs)
    summary["negative_median_timing_benefit"] = [metric for metric, stat in summary["paired_ratios"].items()
                                                  if stat.get("median", 1) < 1]
    summary["interpretation"] = "Ratios use this frozen implementation baseline, not the official scoring baseline. Negative benefit and failed runs remain in evidence; no automatic source changes or rollback are performed."
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-binary", type=Path, required=True)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--baseline-lock", type=Path, required=True)
    parser.add_argument("--candidate-binary", type=Path)
    parser.add_argument("--candidate-source", type=Path)
    parser.add_argument("--candidate-manifest", type=Path)
    parser.add_argument("--benchmark-script", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, default=Path(__file__).with_name("cardinality_probe.py"))
    parser.add_argument("--image")
    parser.add_argument("--socket")
    parser.add_argument("--cpuset", default="auto", help="Fixed CPU IDs for both variants; auto selects the first two CPUs allowed to the Linux driver")
    parser.add_argument("--workloads", choices=("both", "vector128", "cardinality"), default="both")
    parser.add_argument("--cardinality-rows", type=int, default=1000000)
    parser.add_argument("--cardinality-kinds", default="scalar,vector4")
    parser.add_argument("--batch-rows", type=int, default=1000)
    parser.add_argument("--transaction-rows", type=int, default=25000)
    parser.add_argument("--stage-seconds", type=float, default=120)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", help="Verify identities and SQL only, without oracle computation or database execution")
    args = parser.parse_args()
    if not args.prepare_only and not all((args.candidate_binary, args.candidate_source, args.candidate_manifest)):
        parser.error("Actual paired execution requires frozen candidate binary/source/manifest")
    if not 1000 <= args.cardinality_rows <= 2000000 or args.batch_rows <= 0 or args.transaction_rows <= 0 or args.stage_seconds <= 0:
        parser.error("Invalid bounded cardinality size, batch size, transaction size or stage budget")
    kinds = args.cardinality_kinds.split(",")
    if len(set(kinds)) != len(kinds) or any(kind not in ("scalar", "vector4") for kind in kinds):
        parser.error("Cardinality kinds must be a unique comma-separated list of scalar,vector4")
    cpuset = args.cpuset
    if cpuset == "auto":
        affinity = sorted(os.sched_getaffinity(0))
        if len(affinity) < 2:
            parser.error("At least two allowed CPUs are required")
        cpuset = ",".join(map(str, affinity[:2]))
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory is not empty; use a new evidence directory to preserve prior runs")
    output.mkdir(parents=True, exist_ok=True)
    tools_dir = output / "tools"
    tools_dir.mkdir()
    baseline = identity(args.baseline_binary, args.baseline_source, args.baseline_manifest)
    lock = json.loads(args.baseline_lock.read_text(encoding="utf-8-sig"))
    if baseline["binary_sha256"] != lock["baseline_binary_sha256"]:
        raise ValueError("Baseline binary does not match the independently frozen baseline lock")
    candidate = identity(args.candidate_binary, args.candidate_source, args.candidate_manifest) if all((args.candidate_binary, args.candidate_source, args.candidate_manifest)) else None
    frozen_tools = {}
    for name, source in (("paired_benchmark.py", Path(__file__)), ("oracle.py", args.oracle), ("benchmark_local.py", args.benchmark_script), ("cardinality_probe.py", args.adapter)):
        if not source.is_file():
            if args.prepare_only and name == "cardinality_probe.py":
                frozen_tools[name] = {"not_available": True}
                continue
            raise FileNotFoundError(source)
        destination = tools_dir / name
        shutil.copyfile(source, destination)
        frozen_tools[name] = {"source_path": str(source.resolve()), "frozen_path": str(destination), "sha256": sha256_file(destination)}
    oracle = load_module("paired_frozen_oracle", tools_dir / "oracle.py")
    batches, queries = oracle.generate_sql()
    sql = [oracle.CREATE_SQL] + batches + queries
    workload_capture = oracle.verify_workload(tools_dir / "benchmark_local.py", Path(baseline["binary_path"]), sql)
    with gzip.open(output / "workload.sql.gz", "wb") as stream:
        stream.write(("\n".join(sql) + "\n").encode("utf-8"))
    metadata = {
        "scope": "Controlled local paired benchmark with independent correctness checks; not official scoring or submission",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python_version": sys.version, "platform": platform.platform(),
        "baseline": baseline, "candidate": candidate,
        "baseline_lock_path": str(args.baseline_lock.resolve()), "baseline_lock_sha256": sha256_file(args.baseline_lock),
        "tools": frozen_tools,
        "workload_sql_sha256": oracle.sequence_sha256(sql),
        "write_sql_sha256": oracle.sequence_sha256(batches), "query_sql_sha256": oracle.sequence_sha256(queries),
        "query_statement_sha256": [oracle.statement_sha256(query) for query in queries],
        "workload_capture": workload_capture,
        "required_limits": {"memory.max": MEMORY_BYTES, "memory.swap.max": 0, "cpu.max": f"{CPU_QUOTA} {CPU_PERIOD}"},
        "fixed_cpuset": cpuset,
        "order": PAIR_ORDERS, "warmup_query_count": WARMUP_QUERIES,
        "prepare_only": args.prepare_only,
        "selected_workloads": args.workloads,
        "high_cardinality_scope": {"rows": args.cardinality_rows, "kinds": kinds, "batch_rows": args.batch_rows,
                                   "transaction_rows": args.transaction_rows, "stage_seconds": args.stage_seconds,
                                   "note": "Three alternating pairs per selected schema at a common completed size; boundary expansion is a separate diagnostic, not repeated OOM attempts."},
        "cache_note": "Fresh process and independent data directory per variant/run; no global drop_caches. First read is process-first, not OS-cold.",
    }
    write_json(output / "preflight.json", metadata)
    if args.prepare_only:
        print(json.dumps({"prepared": True, "executed_database": False, "evidence_directory": str(output)}, indent=2))
        return 0
    adapter = load_module("paired_frozen_cgroup_adapter", tools_dir / "cardinality_probe.py")
    truth = None
    workloads = {}
    if args.workloads in ("both", "vector128"):
        truth, oracle_info = prepare_oracle(oracle, batches, queries)
        metadata["oracle"] = oracle_info
        write_json(output / "oracle-truth.json", truth)
        workloads["vector128"] = None
    if args.workloads in ("both", "cardinality"):
        for kind in kinds:
            workload = prepare_cardinality_workload(kind, args.cardinality_rows, args.batch_rows, args.transaction_rows)
            name = f"cardinality-{kind}-{args.cardinality_rows}"
            workloads[name] = workload
            with gzip.open(output / (name + ".sql.gz"), "wb") as stream:
                for _, commands in workload["stages"]:
                    for command in commands:
                        stream.write((command["sql"] + "\n").encode())
                for command in workload["restart"]:
                    stream.write((command["sql"] + "\n").encode())
            write_json(output / (name + "-oracle.json"), {
                "scope": "Input generated and expectations prepared before all DB runs; deterministic integer-valued FP32 input, independent FP64 exhaustive filtered TopK",
                **{key: value for key, value in workload.items() if key not in ("stages", "restart")},
                "expectations": [{"phase": phase, **{key: value for key, value in command.items() if key != "sql"}}
                                 for phase, commands in workload["stages"] + [("restart", workload["restart"])] for command in commands],
            })
    write_json(output / "preflight.json", metadata)
    variants = {"baseline": baseline, "candidate": candidate}
    all_runs = {name: [] for name in workloads}
    def combined_summary():
        summaries = {name: summarize(runs) for name, runs in all_runs.items()}
        return {"workloads": summaries, "all_planned_runs_passed": all(value["all_six_runs_passed"] for value in summaries.values()),
                "interpretation": "Actual frozen baseline and candidate, matched resources/consumer/inputs. These are local evidence, not official performance points. All failed and negative-benefit runs are retained."}
    for workload_name, workload in workloads.items():
        for pair_index, order in enumerate(PAIR_ORDERS):
            for order_index, variant in enumerate(order):
                label = f"{workload_name}-pair-{pair_index + 1}-{order_index + 1}-{variant}"
                print(f"Starting {label}", flush=True)
                image, socket = args.image or adapter.IMAGE, args.socket or adapter.SOCKET
                if workload is None:
                    result = run_one(adapter, label, variant, variants[variant], output / label, batches, queries, truth, oracle, image, socket, cpuset)
                else:
                    result = run_cardinality(adapter, label, variant, variants[variant], output / label, workload, image, socket, cpuset, args.stage_seconds)
                result["pair_index"] = pair_index
                result["order_index"] = order_index
                all_runs[workload_name].append(result)
                write_json(output / label / "run.json", result)
                write_json(output / "summary.json", combined_summary())
                print(json.dumps({"run": label, "passed": result["passed"], "failure": result["failure"], "timings": result["timings"]}), flush=True)
    metadata["identities_after"] = {
        variant: identity(value["binary_path"], value["source"]["source_directory"], value["source"]["manifest_path"]) for variant, value in variants.items()
    }
    metadata["identities_unchanged"] = all(metadata["identities_after"][variant] == value for variant, value in variants.items())
    write_json(output / "preflight.json", metadata)
    summary = combined_summary()
    summary["identities_unchanged"] = metadata["identities_unchanged"]
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_planned_runs_passed"] and metadata["identities_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
