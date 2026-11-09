#!/usr/bin/env python3
"""Audit every query in benchmark_local.py using an independent NumPy oracle.

This is a correctness/evidence run, not a performance measurement or official
test. Workload dry-run capture proves SQL identity only; the actual database
checks execute the separately supplied, frozen binary against a fresh directory.
NumPy is an audit-only dependency and is not needed by the database executable.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import select
import subprocess
import sys
import tempfile
import types


SEED = 3179
ROWS = 10000
DIMENSION = 128
QUERY_COUNT = 1000
BATCH_SIZE = 100
TOP_K = 10
DISTANCE_ATOL = 1e-10
DISTANCE_RTOL = 1e-12
CREATE_SQL = "CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR(128));"


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def statement_sha256(statement):
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def sequence_sha256(statements):
    digest = hashlib.sha256()
    for statement in statements:
        digest.update(statement.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def generate_sql():
    # Match the original RNG draw order, round(..., 6), json.dumps options, and
    # SQL construction exactly. --verify-workload checks each emitted string.
    rng = random.Random(SEED)
    batches = []
    for begin in range(0, ROWS, BATCH_SIZE):
        tuples = []
        for i in range(begin, min(begin + BATCH_SIZE, ROWS)):
            vector = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)], separators=(",", ":"))
            tuples.append(f"({i},'g{i % 5}','{vector}')")
        batches.append("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
    queries = []
    for i in range(QUERY_COUNT):
        vector = json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)], separators=(",", ":"))
        where = f" WHERE grp='g{i % 5}'" if i % 2 else ""
        queries.append(f"SELECT id,L2_DISTANCE(v,'{vector}') AS d FROM bench{where} ORDER BY d LIMIT 10;")
    return batches, queries


def verify_workload(benchmark_script, binary_argument, expected):
    """Run the actual benchmark Python entrypoint with an inert SQL recorder.

    No database process is launched by this function, and its fabricated
    transport acknowledgements must never be presented as execution evidence.
    """
    spec = importlib.util.spec_from_file_location("frozen_benchmark_for_sql_capture", benchmark_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = []

    class InertTransport:
        def __init__(self, *args, **kwargs):
            self.pid = os.getpid()  # Only supplies the benchmark's /proc read.
            self.returncode = 0
            self.stdin = self
            self.stdout = self
            self.stderr = io.StringIO()
            self.next_response = ""

        def write(self, data):
            if not isinstance(data, str) or not data.endswith("\n"):
                raise AssertionError("Unexpected benchmark SQL transport framing")
            statement = data[:-1]
            captured.append(statement)
            rows = [[i, i] for i in range(TOP_K)] if statement.startswith("SELECT ") else []
            self.next_response = json.dumps({"ok": True, "columns": [], "rows": rows, "affected": 0}) + "\n"
            return len(data)

        def flush(self):
            pass

        def readline(self):
            response = self.next_response
            self.next_response = ""
            return response

        def close(self):
            pass

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def kill(self):
            raise AssertionError("The dry-run transport should not be killed")

    module.subprocess = types.SimpleNamespace(Popen=InertTransport, PIPE=subprocess.PIPE)
    old_argv = sys.argv
    try:
        sys.argv = [str(benchmark_script), "--binary", str(binary_argument), "--rows", str(ROWS), "--queries", str(QUERY_COUNT)]
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
    finally:
        sys.argv = old_argv
    if captured != expected:
        for index, (actual, wanted) in enumerate(zip(captured, expected)):
            if actual != wanted:
                raise AssertionError(f"Workload SQL mismatch at statement {index}: expected {statement_sha256(wanted)}, captured {statement_sha256(actual)}")
        raise AssertionError(f"Workload statement count mismatch: {len(captured)} != {len(expected)}")
    return {
        "passed": True,
        "statements_compared": len(captured),
        "captured_sequence_sha256": sequence_sha256(captured),
        "scope": "Mock transport compares SQL text only. It does not execute SQL and is not database correctness evidence.",
    }


def parse_oracle_inputs(batches, queries, np):
    # Decode the exact submitted SQL literals independently of the database's
    # parser, row serializer, vector-distance implementation, or cache.
    tuple_pattern = re.compile(r"\(([0-9]+),'g([0-4])','(\[[^\]]*\])'\)")
    ids, groups, raw_vectors = [], [], []
    for batch in batches:
        prefix = "INSERT INTO bench VALUES "
        if not batch.startswith(prefix) or not batch.endswith(";"):
            raise AssertionError("Unexpected insertion SQL")
        body = batch[len(prefix):-1]
        matches = list(tuple_pattern.finditer(body))
        if ",".join(match.group(0) for match in matches) != body:
            raise AssertionError("The audit parser did not consume the complete insertion SQL")
        for match in matches:
            vector = json.loads(match.group(3))
            if len(vector) != DIMENSION:
                raise AssertionError("Unexpected inserted vector dimension")
            ids.append(int(match.group(1)))
            groups.append(int(match.group(2)))
            raw_vectors.append(vector)
    if ids != list(range(ROWS)) or groups != [i % 5 for i in range(ROWS)]:
        raise AssertionError("Unexpected inserted IDs or filter groups")
    # Stored coordinates and query literals are first quantized to IEEE float32,
    # then promoted to float64 for independent exhaustive L2 computation.
    stored = np.asarray(raw_vectors, dtype=np.float32)
    query_pattern = re.compile(r"SELECT id,L2_DISTANCE\(v,'(\[[^\]]*\])'\) AS d FROM bench(?: WHERE grp='g([0-4])')? ORDER BY d LIMIT 10;")
    query_inputs = []
    for index, query in enumerate(queries):
        match = query_pattern.fullmatch(query)
        if not match:
            raise AssertionError("The audit parser did not consume a complete query SQL")
        raw = json.loads(match.group(1))
        group = int(match.group(2)) if match.group(2) is not None else None
        if len(raw) != DIMENSION or group != (index % 5 if index % 2 else None):
            raise AssertionError("Unexpected query vector or predicate")
        query_inputs.append((np.asarray(raw, dtype=np.float32).astype(np.float64), group))
    return np.asarray(ids, dtype=np.int64), np.asarray(groups, dtype=np.int64), stored.astype(np.float64), query_inputs


class Client:
    def __init__(self, binary, directory):
        self.errors = tempfile.TemporaryFile(mode="w+b")
        self.proc = subprocess.Popen(
            [str(binary), "--data-dir", str(directory), "--dev-protocol"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
        )
        self.responses = hashlib.sha256()

    def execute(self, statement):
        self.proc.stdin.write((statement + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        readable, _, _ = select.select([self.proc.stdout], [], [], 120)
        if not readable:
            raise RuntimeError("No database response within audit timeout (120 seconds)")
        response = self.proc.stdout.readline()
        if not response:
            raise RuntimeError("Database exited before its audit response")
        self.responses.update(response)
        parsed = json.loads(response)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
            raise RuntimeError("Invalid development-protocol response")
        return parsed

    def close(self):
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()
        self.errors.seek(0)
        error_text = self.errors.read().decode("utf-8", errors="replace")
        self.errors.close()
        return self.proc.returncode, error_text


def audit_query(index, query, response, ids, groups, vectors, query_input, np):
    query_vector, group = query_input
    # Every database row is evaluated. Filtered truth is derived within the
    # eligible set, not by filtering a previously selected global TopK.
    difference = vectors - query_vector
    distances = np.sqrt(np.sum(difference * difference, axis=1, dtype=np.float64))
    eligible = np.arange(ROWS) if group is None else np.flatnonzero(groups == group)
    ordered = eligible[np.lexsort((ids[eligible], distances[eligible]))]
    expected_ids = [int(key) for key in ids[ordered[:TOP_K]]]
    issues = []
    output_ids = []
    max_error = None
    if response.get("ok") is not True:
        issues.append("database_error_response")
        rows = []
    else:
        rows = response.get("rows")
        if not isinstance(rows, list):
            issues.append("missing_row_array")
            rows = []
    if len(rows) != len(expected_ids):
        issues.append("incorrect_result_count")
    valid_id_set = set()
    for row_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 2:
            issues.append(f"row_{row_index}:invalid_row_shape")
            continue
        key, distance = row
        if not isinstance(key, int) or isinstance(key, bool):
            issues.append(f"row_{row_index}:non_integer_id")
            continue
        output_ids.append(key)
        if key < 0 or key >= ROWS:
            issues.append(f"row_{row_index}:unknown_id")
            continue
        if key in valid_id_set:
            issues.append(f"row_{row_index}:duplicate_id")
        valid_id_set.add(key)
        if group is not None and int(groups[key]) != group:
            issues.append(f"row_{row_index}:filter_violation")
        if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance):
            issues.append(f"row_{row_index}:invalid_distance")
            continue
        truth_distance = float(distances[key])
        error = abs(float(distance) - truth_distance)
        max_error = error if max_error is None else max(max_error, error)
        if error > DISTANCE_ATOL + DISTANCE_RTOL * abs(truth_distance):
            issues.append(f"row_{row_index}:distance_mismatch")
    if set(output_ids) != set(expected_ids):
        issues.append("topk_membership_mismatch")
    if output_ids != expected_ids:
        issues.append("topk_order_mismatch")
    recall = len(valid_id_set.intersection(expected_ids)) / len(expected_ids)
    return {
        "query_index": index,
        "query_sha256": statement_sha256(query),
        "filter_group": None if group is None else f"g{group}",
        "response_ok": response.get("ok") is True,
        "passed": not issues,
        "issues": issues,
        "expected_ids": expected_ids,
        "returned_ids": output_ids,
        "recall_at_10": recall,
        "maximum_absolute_distance_error": max_error,
    }


def recall_summary(results, filtered):
    selected = [row for row in results if (row["filter_group"] is not None) == filtered]
    recalls = [row["recall_at_10"] for row in selected]
    return {
        "queries_checked": len(selected),
        "expected_query_count": QUERY_COUNT // 2,
        "queries_passed_all_checks": sum(row["passed"] for row in selected),
        "minimum_recall_at_10": min(recalls) if recalls else None,
        "mean_recall_at_10": sum(recalls) / len(recalls) if recalls else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--benchmark-script", type=Path, default=Path(__file__).with_name("benchmark_local.py"))
    parser.add_argument("--verify-workload", action="store_true", help="Compare all generated SQL against an inert capture of the actual benchmark script")
    parser.add_argument("--workload-only", action="store_true", help="Generate/verify SQL identities without executing any database")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.workload_only and (args.binary is None or not args.binary.is_file()):
        parser.error("A valid frozen --binary is required for the actual correctness audit")
    if not args.benchmark_script.is_file():
        parser.error("--benchmark-script does not exist")
    benchmark_script = args.benchmark_script.resolve()
    binary = args.binary.resolve() if args.binary else None
    batches, queries = generate_sql()
    sequence = [CREATE_SQL] + batches + queries
    report = {
        "scope": "Independent local correctness audit of benchmark workload; not an official assessment or performance result",
        "records": ROWS, "dimension": DIMENSION, "queries": QUERY_COUNT,
        "batch_size": BATCH_SIZE, "seed": SEED, "top_k": TOP_K,
        "python_version": sys.version,
        "platform": platform.platform(),
        "oracle_script_sha256": file_sha256(Path(__file__).resolve()),
        "benchmark_script_sha256": file_sha256(benchmark_script),
        "binary_sha256_before": file_sha256(binary) if binary else None,
        "sql_hash_encoding": "UTF-8; per-statement SHA excludes terminator newline; sequence SHA concatenates each SQL statement followed by one LF",
        "create_sql_sha256": statement_sha256(CREATE_SQL),
        "write_sql_sha256": sequence_sha256(batches),
        "query_sql_sha256": sequence_sha256(queries),
        "workload_sql_sha256": sequence_sha256(sequence),
        "write_statement_sha256": [statement_sha256(statement) for statement in batches],
        "query_statement_sha256": [statement_sha256(statement) for statement in queries],
        "workload_capture": None,
        "actual_database_executed": False,
    }
    try:
        if args.verify_workload:
            report["workload_capture"] = verify_workload(benchmark_script, binary or Path(sys.executable), sequence)
        if not args.workload_only:
            import numpy as np
            report["numpy_version"] = np.__version__
            report["oracle"] = {
                "method": "Parse exact SQL vector JSON literals; cast coordinates to float32, promote to float64; exhaustive L2 for all rows; apply predicate, lexsort(distance, primary_key)",
                "distance_absolute_tolerance": DISTANCE_ATOL,
                "distance_relative_tolerance": DISTANCE_RTOL,
                "sampling": "none; every one of 1000 queries and every returned distance is checked",
                "timing": "No audit or oracle time is reported as a performance score",
            }
            ids, groups, vectors, query_inputs = parse_oracle_inputs(batches, queries, np)
            details = []
            report["query_results"] = details
            report["write_batches_acknowledged"] = 0
            with tempfile.TemporaryDirectory(prefix="mvdb-performance-correctness-audit-") as directory:
                client = Client(binary, directory)
                report["actual_database_executed"] = True
                try:
                    created = client.execute(CREATE_SQL)
                    if not created["ok"]:
                        raise RuntimeError(f"Table creation failed: {created!r}")
                    for batch in batches:
                        response = client.execute(batch)
                        if not response["ok"]:
                            raise RuntimeError(f"Data loading failed: {response!r}")
                        report["write_batches_acknowledged"] += 1
                    for index, query in enumerate(queries):
                        result = client.execute(query)
                        checked = audit_query(index, query, result, ids, groups, vectors, query_inputs[index], np)
                        details.append(checked)
                        if not checked["passed"]:
                            print(f"Query {index} failed: {checked['issues']}", file=sys.stderr)
                        elif (index + 1) % 100 == 0:
                            print(f"Independently checked {index + 1}/{QUERY_COUNT} queries", file=sys.stderr)
                finally:
                    report["database_exit_code"], report["database_stderr"] = client.close()
                    report["database_responses_sha256"] = client.responses.hexdigest()
            report["binary_sha256_after"] = file_sha256(binary)
            if report["binary_sha256_after"] != report["binary_sha256_before"]:
                raise RuntimeError("Binary content changed during audit")
            report["queries_response_ok"] = sum(row["response_ok"] for row in details)
            report["queries_passed_all_checks"] = sum(row["passed"] for row in details)
            report["queries_failed_checks"] = sum(not row["passed"] for row in details)
            report["queries_not_run"] = QUERY_COUNT - len(details)
            report["filtered"] = recall_summary(details, True)
            report["unfiltered"] = recall_summary(details, False)
            errors = [row["maximum_absolute_distance_error"] for row in details if row["maximum_absolute_distance_error"] is not None]
            report["maximum_absolute_distance_error"] = max(errors) if errors else None
            report["passed"] = len(details) == QUERY_COUNT and all(row["passed"] for row in details) and report["database_exit_code"] == 0
        else:
            report["passed"] = bool(report["workload_capture"] and report["workload_capture"]["passed"])
    except Exception as error:
        report["passed"] = False
        report["audit_error"] = f"{type(error).__name__}: {error}"
        print(report["audit_error"], file=sys.stderr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    summary_keys = ("scope", "passed", "actual_database_executed", "binary_sha256_before", "workload_sql_sha256", "queries_response_ok", "queries_passed_all_checks", "queries_failed_checks", "queries_not_run", "filtered", "unfiltered", "maximum_absolute_distance_error", "audit_error")
    print(json.dumps({**{key: report[key] for key in summary_keys if key in report}, "report": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
