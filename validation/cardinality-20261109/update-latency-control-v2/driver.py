"""Bounded sampler on/off diagnostic; no production changes or score claim."""
import argparse
import hashlib
import heapq
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import time

BASE_SHA = "747092fd68833b52ec80020e050d4586d443220f513d6b3d932ab3e25eea072f"
CANDIDATE_SHA = "78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c"
ADAPTER_SHA = "d17b60f2b86c582cd870edf5118d40c255069b2b37840caaf07cb08d8a850525"
WAL_SHA = "6fd59dd3ccfb5221314cb6a0794df0c333e927da6d72ae3955b6b66244a77d93"
ORDERS = (("baseline", "candidate"), ("candidate", "baseline"), ("baseline", "candidate"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def distribution(values):
    mean = statistics.mean(values) if values else None
    return {"values": values, "median": statistics.median(values) if values else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "coefficient_of_variation": statistics.pstdev(values) / mean if mean else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--wal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    identities = {"baseline": {"path": str(args.baseline.resolve()), "sha256": sha(args.baseline)},
                  "candidate": {"path": str(args.candidate.resolve()), "sha256": sha(args.candidate)}}
    assert identities["baseline"]["sha256"] == BASE_SHA
    assert identities["candidate"]["sha256"] == CANDIDATE_SHA
    assert sha(args.adapter) == ADAPTER_SHA
    assert sha(args.wal) == WAL_SHA
    output = args.output.resolve()
    assert not output.exists() or not any(output.iterdir()), "New output directory required"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, output / "driver.py")
    shutil.copyfile(args.adapter, output / "adapter.py")
    spec = importlib.util.spec_from_file_location("frozen_update_adapter", output / "adapter.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    class Database(adapter.ContainerDatabase):
        def __init__(self, *positional, sampler, **keywords):
            self.sampler_enabled = sampler
            super().__init__(*positional, **keywords)

        def _monitor(self):
            if self.sampler_enabled:
                return super()._monitor()
            # Preserve constructor, query consumer, synchronous phase captures,
            # and cleanup. Only background sampling is disabled in this control.
            return

    source_adaptation = "Subclass overrides _monitor: sampler=on delegates unmodified monitor; off returns without background reads. No production or adapter source edits. cpu.stat/cpu.pressure/io.pressure are read synchronously outside each measured SQL round trip."
    metadata = {"scope": "Diagnostic comparison, not official benchmark and not a replacement for the original 18 runs",
                "identities": identities, "adapter_sha256": ADAPTER_SHA,
                "driver_sha256": sha(__file__), "initial_wal_sha256": WAL_SHA,
                "initial_wal_bytes": args.wal.stat().st_size, "repetitions_per_run": 5,
                "num_runs": 12, "cpuset": "0,1", "memory_max": 134217728, "swap_max": 0,
                "cpu_max": "200000 100000", "python_switchinterval_seconds": sys.getswitchinterval(),
                "adapter_difference": source_adaptation,
                "fixture_policy": "Each run copies the same frozen 1m vector4 WAL into a fresh ext4 directory and fsyncs it outside timing. No drop_caches. Copying/recovery can change page-cache ownership and allocator history relative to original write-then-query runs; this control cannot retroactively replace them.",
                "timing": "Separate SQL send-to-complete-JSON-response wall times include the common Python/Docker consumer. All truth and comparisons occur outside measured intervals. CPU/pressure/io phase captures are outside timers.",
                "limitations": "A sampler effect, if observed, supports an observer-cost explanation for this control but does not prove Python GIL is the sole cause of earlier results. io.stat volumes are not I/O service latency or finalized physical-I/O attribution.",
                "prepare_only": args.prepare_only, "runs": []}
    save(output / "preflight.json", metadata)
    if args.prepare_only:
        print(json.dumps({"prepared": True, "executed_database": False, "driver_sha256": metadata["driver_sha256"]}))
        return 0
    # Independent exhaustive reference is computed once before every measured run.
    top = heapq.nsmallest(8, ((math.sqrt((key % 31 - .5) ** 2 + (key % 17 - 1.5) ** 2
                                       + (key % 7 - 2.5) ** 2 + (key % 3 - 1.) ** 2), key)
                           for key in range(1000000) if key % 97 >= 47))
    vector_expected = [[key, distance] for distance, key in top]
    scan_expected = [[96 + i * 97, 96] for i in range(8)]
    scan_sql = "SELECT id,x FROM items WHERE x>=0 ORDER BY x DESC,id ASC LIMIT 8;"
    vector_sql = "SELECT id,L2_DISTANCE(v,'[0.5,1.5,2.5,1]') AS d FROM items WHERE x>=47 ORDER BY d,id LIMIT 8;"
    precondition = [("scalar_scan", scan_sql, scan_expected)] * 4 + [("vector_topk", vector_sql, vector_expected)] * 4
    overall_deadline = time.monotonic() + 420

    def capture(db, label, result):
        value = dict(db.capture(label) or {})
        for field in ("cpu.stat", "cpu.pressure", "io.pressure"):
            try:
                value[field] = (db.cg / field).read_text().strip()
            except OSError as error:
                value[field + "_error"] = str(error)
        result["snapshots"].append({"label": label, "values": value})
        return value

    def execute(db, result, phase, sql, expected=None, affected=None, measure=True):
        if time.monotonic() >= overall_deadline:
            raise TimeoutError("Diagnostic fixed total budget exceeded")
        capture(db, phase + ":before", result)
        started = time.monotonic()
        response = db.query(sql, timeout=20)
        ended = time.monotonic()
        capture(db, phase + ":after", result)
        result["responses"].append({"phase": phase, "sql": sql, "response": response,
                                    "expected_rows": expected, "expected_affected": affected,
                                    "start_monotonic": started, "end_monotonic": ended,
                                    "elapsed_seconds": ended - started, "target_measurement": measure})

    for pair, order in enumerate(ORDERS):
        modes = ("on", "off") if pair != 1 else ("off", "on")
        for mode in modes:
            for variant in order:
                label = f"pair-{pair + 1}-sampler-{mode}-{variant}"
                directory = output / label / "data"
                directory.mkdir(parents=True)
                shutil.copyfile(args.wal, directory / "journal.mvdb")
                with (directory / "journal.mvdb").open("rb") as stream:
                    os.fsync(stream.fileno())
                assert sha(directory / "journal.mvdb") == WAL_SHA
                result = {"label": label, "pair": pair, "sampler": mode, "variant": variant,
                          "data_directory": str(directory), "snapshots": [], "responses": [], "passed": False}
                db = None
                print("Starting " + label, flush=True)
                try:
                    db = Database(Path(identities[variant]["path"]), directory, label=label, cpuset="0,1", sampler=mode == "on")
                    execute(db, result, "first_pk", "SELECT id,x FROM items WHERE id=0;", [[0, 0]])
                    for iteration in range(5):
                        for index, (name, sql, expected) in enumerate(precondition):
                            execute(db, result, f"iteration-{iteration}:pre-{index}-{name}", sql, expected, measure=False)
                        execute(db, result, f"iteration-{iteration}:update", "UPDATE items SET x=999 WHERE id=0;", affected=1)
                        execute(db, result, f"iteration-{iteration}:verify", "SELECT x FROM items WHERE id=0;", [[999]])
                        execute(db, result, f"iteration-{iteration}:restore", "UPDATE items SET x=0 WHERE id=0;", affected=1)
                        execute(db, result, f"iteration-{iteration}:restore-verify", "SELECT x FROM items WHERE id=0;", [[0]])
                    execute(db, result, "pending-begin", "BEGIN;", measure=False)
                    execute(db, result, "pending-update", "UPDATE items SET x=777 WHERE id<25000;", affected=25000, measure=False)
                    sequence = [("rollback", "ROLLBACK;", None, None),
                                ("rollback-read", "SELECT x FROM items WHERE id=0;", [[0]], None),
                                ("begin", "BEGIN;", None, None),
                                ("update", "UPDATE items SET x=666 WHERE id=0;", None, 1),
                                ("commit", "COMMIT;", None, None),
                                ("read", "SELECT x FROM items WHERE id=0;", [[666]], None),
                                ("restore", "UPDATE items SET x=0 WHERE id=0;", None, 1)]
                    for name, sql, expected, affected in sequence:
                        execute(db, result, "transaction:" + name, sql, expected, affected)
                except Exception as error:
                    result["failure"] = f"{type(error).__name__}: {error}"
                finally:
                    if db is not None:
                        db.close(kill="failure" in result)
                        result["container_record"] = db.record
                issues = []
                for entry in result["responses"]:
                    actual, expected = entry["response"].get("rows"), entry["expected_rows"]
                    if expected is not None:
                        if not isinstance(actual, list) or len(actual) != len(expected):
                            issues.append(entry["phase"] + ":rows")
                        else:
                            for got, want in zip(actual, expected):
                                if len(got) != len(want) or any((not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)) if isinstance(b, float) else a != b for a, b in zip(got, want)):
                                    issues.append(entry["phase"] + ":value_or_order")
                    if entry["expected_affected"] is not None and entry["response"].get("affected") != entry["expected_affected"]:
                        issues.append(entry["phase"] + ":affected")
                state = result.get("container_record", {}).get("docker_final_state", {})
                result["issues"] = issues
                result["passed"] = not issues and "failure" not in result and state.get("ExitCode") == 0 and not state.get("OOMKilled", False)
                targets = {"update": [], "verify": [], "restore": [], "restore-verify": []}
                for entry in result["responses"]:
                    if entry["phase"].startswith("iteration-"):
                        name = entry["phase"].split(":")[-1]
                        if name in targets:
                            targets[name].append(entry["elapsed_seconds"])
                result["target_distributions"] = {name: distribution(values) for name, values in targets.items()}
                result["first_pk_seconds"] = result["responses"][0]["elapsed_seconds"] if result["responses"] else None
                result["transaction_sql_seconds_sum_excluding_captures"] = sum(entry["elapsed_seconds"] for entry in result["responses"] if entry["phase"].startswith("transaction:"))
                save(output / label / "run.json", result)
                metadata["runs"].append({"label": label, "pair": pair, "sampler": mode, "variant": variant,
                                         "passed": result["passed"], "target_distributions": result["target_distributions"],
                                         "first_pk_seconds": result["first_pk_seconds"],
                                         "transaction_sql_seconds_sum_excluding_captures": result["transaction_sql_seconds_sum_excluding_captures"]})
                save(output / "results.json", metadata)
                print(json.dumps(metadata["runs"][-1]), flush=True)
    metadata["binary_identities_unchanged"] = all(sha(value["path"]) == value["sha256"] for value in identities.values())
    metadata["original_wal_unchanged"] = sha(args.wal) == WAL_SHA
    metadata["paired_ratios"] = {}
    for mode in ("on", "off"):
        measures = {name: [] for name in ("update", "verify", "restore", "restore-verify", "first_pk", "transaction_sql_sum")}
        for pair in range(3):
            matching = {entry["variant"]: entry for entry in metadata["runs"] if entry["sampler"] == mode and entry["pair"] == pair}
            if len(matching) != 2 or not all(entry["passed"] for entry in matching.values()):
                continue
            for name in measures:
                def value(entry):
                    if name == "first_pk": return entry["first_pk_seconds"]
                    if name == "transaction_sql_sum": return entry["transaction_sql_seconds_sum_excluding_captures"]
                    return entry["target_distributions"][name]["median"]
                measures[name].append(value(matching["baseline"]) / value(matching["candidate"]))
        metadata["paired_ratios"][mode] = {name: distribution(values) for name, values in measures.items()}
    metadata["all_runs_passed"] = len(metadata["runs"]) == 12 and all(entry["passed"] for entry in metadata["runs"])
    save(output / "results.json", metadata)
    return 0 if metadata["all_runs_passed"] and metadata["binary_identities_unchanged"] and metadata["original_wal_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
