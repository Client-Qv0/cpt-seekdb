#!/usr/bin/env python3
"""Separate Store-constructor timing on byte-identical WAL fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import struct
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("frozen_adapter", HERE / "probe-v2.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
ROOT = Path("/var/tmp/minivectordb-paired-candidate-v1")
EXPECTED = {"scalar": "f92e203bdbc77625163b648b185d0eeb90c10b726e2b7e16bb89aba315c9ee30",
            "vector4": "6fd59dd3ccfb5221314cb6a0794df0c333e927da6d72ae3955b6b66244a77d93"}
ORDERS = [("baseline", "candidate"), ("candidate", "baseline"), ("baseline", "candidate")]


def one(kind, pair, position, version, fixture):
    directory = Path(tempfile.mkdtemp(prefix=f"mvdb-recovery-{kind}-p{pair}-{version}-", dir="/var/tmp"))
    journal = directory / "journal.mvdb"
    shutil.copyfile(fixture, journal)
    before = adapter.sha256(journal)
    if before != EXPECTED[kind]:
        raise AssertionError("Copied fixture SHA mismatch")
    binary = HERE / f"recovery-helper-{version}"
    result = {"kind": kind, "pair": pair, "position": position, "variant": version,
              "rows": 1000000, "fixture": str(fixture), "copy": str(journal),
              "wal_bytes": journal.stat().st_size, "wal_before_sha256": before,
              "helper_sha256": adapter.sha256(binary), "passed": False}
    db = None
    try:
        started = time.monotonic()
        db = adapter.ContainerDatabase(binary, directory, label=f"recovery-{kind}-pair{pair}-{version}", cpuset="0,1")
        ready = db.query("READY", timeout=60)
        wall = time.monotonic() - started
        result["ready"] = ready
        result["launch_to_ready_seconds"] = wall
        result["store_constructor_seconds"] = ready["restore_nanoseconds"] / 1e9
        result["wall_outside_constructor_seconds"] = wall - result["store_constructor_seconds"]
        actual = db.capture("ready_before_verification")
        if actual["cpuset.cpus.effective"] != "0-1":
            raise AssertionError("Unexpected actual cpuset")
        result["settled_memory"] = []
        for i in range(3):
            time.sleep(.5)
            result["settled_memory"].append(adapter.compact(db.capture(f"ready_settled_{i + 1}")))
        result["settling_excluded_from_restore_and_launch_time_seconds"] = 1.5
        keys = sorted({0, 99, 100, 999999, 500000, *[i * 999999 // 31 for i in range(32)]})
        samples = []
        for key in keys:
            sample = db.query(f"GET items {key}", timeout=60)
            expected = struct.pack("<qq", key, key % 97)
            if kind == "vector4":
                expected += struct.pack("<ffff", key % 31, key % 17, key % 7, key % 3)
            if sample.get("found") is not True or sample.get("hex") != expected.hex():
                raise AssertionError(f"Restored key/value mismatch for {key}")
            samples.append(sample)
        absent = db.query("GET items 1000000", timeout=60)
        if absent["found"]:
            raise AssertionError("Unexpected row beyond fixture range")
        started_scan = time.monotonic()
        scanned = db.query("SCAN items", timeout=60)
        result["verification_scan_seconds_not_restore"] = time.monotonic() - started_scan
        if (scanned["count"] != 1000000 or scanned["min_key"] != 0 or scanned["max_key"] != 999999
                or scanned["payload_bytes"] != 1000000 * (32 if kind == "vector4" else 16)):
            raise AssertionError("Restored full row count/domain/payload length mismatch")
        result["point_samples"] = samples
        result["full_scan_summary"] = scanned
        db.capture("verification_complete")
        result["passed"] = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        if db:
            db.close(kill=not result["passed"])
            result["container"] = db.record
        result["wal_after_sha256"] = adapter.sha256(journal)
        if result["wal_after_sha256"] != before:
            result["passed"] = False
            result["wal_changed"] = True
        if result["passed"]:
            shutil.rmtree(directory)
            result["data_cleaned"] = True
    return result


def summarize(runs):
    result = []
    for kind in EXPECTED:
        records = [r for r in runs if r["kind"] == kind]
        if len(records) != 6 or not all(r["passed"] for r in records):
            continue
        digests = {r["full_scan_summary"]["fnv1a64_noncryptographic"] for r in records}
        if len(digests) != 1:
            raise AssertionError("Cross-version full scan content digest mismatch")
        paired = []
        for pair in range(1, 4):
            b = next(r for r in records if r["pair"] == pair and r["variant"] == "baseline")
            c = next(r for r in records if r["pair"] == pair and r["variant"] == "candidate")
            paired.append({"pair": pair,
                           "constructor_candidate_over_baseline": c["store_constructor_seconds"] / b["store_constructor_seconds"],
                           "launch_wall_candidate_over_baseline": c["launch_to_ready_seconds"] / b["launch_to_ready_seconds"]})
        medians = {}
        for version in ("baseline", "candidate"):
            selected = [r for r in records if r["variant"] == version]
            medians[version] = {}
            for field in ("store_constructor_seconds", "launch_to_ready_seconds", "wall_outside_constructor_seconds"):
                values = [r[field] for r in selected]
                medians[version][field] = {"median": statistics.median(values), "min": min(values), "max": max(values), "all": values}
            for field in ("restore_user_microseconds", "restore_system_microseconds"):
                medians[version][field] = statistics.median(r["ready"][field] for r in selected)
        result.append({"kind": kind, "paired_ratios": paired, "medians": medians,
                       "median_constructor_ratio": statistics.median(r["constructor_candidate_over_baseline"] for r in paired),
                       "full_scan_digest_matches_all_six": True})
    return result


result = {"driver_sha256": adapter.sha256(__file__), "adapter_sha256": adapter.sha256(HERE / "probe-v2.py"),
          "helper_build_manifest_sha256": adapter.sha256(HERE / "recovery-helper-build-manifest.json"),
          "pair_orders": ORDERS, "runs": [], "memory_max": 134217728, "swap_max": 0,
          "cpu_max": "200000 100000", "cpuset": "0,1", "official_benchmark": False,
          "scope": "Separate helper using frozen storage implementation; not production executable end-to-end performance.",
          "limits": ["Store constructor chrono excludes Docker/client launch and all row verification.",
                     "Outside-constructor wall residual includes Docker launch/client synchronization/response, not a pure Docker launch metric.",
                     "Fixture copy and SHA reading prepopulate file cache outside DB cgroup; this is not an OS-cold experiment.",
                     "Row verification checks every row count/length and sampled exact bytes; FNV is cross-version corroboration, not a cryptographic independent full-data oracle.",
                     "Shared-device raw IO counters are uncalibrated."]}
pid = None
try:
    if not {0, 1}.issubset(os.sched_getaffinity(0)):
        raise RuntimeError("CPU 0,1 are not available")
    pid = adapter.start_daemon()
    for kind in EXPECTED:
        fixture = ROOT / f"cardinality-{kind}-1000000-pair-1-1-baseline/data/journal.mvdb"
        counterpart = ROOT / f"cardinality-{kind}-1000000-pair-1-2-candidate/data/journal.mvdb"
        if adapter.sha256(fixture) != EXPECTED[kind] or adapter.sha256(counterpart) != EXPECTED[kind]:
            raise AssertionError("Original paired fixtures are not the expected identical bytes")
        for pair, order in enumerate(ORDERS, 1):
            for position, version in enumerate(order, 1):
                entry = one(kind, pair, position, version, fixture)
                result["runs"].append(entry)
                (HERE / "recovery-diagnostic-results.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps({k: entry.get(k) for k in ("kind", "pair", "variant", "passed", "store_constructor_seconds", "launch_to_ready_seconds", "ready", "error")}), flush=True)
                if not entry["passed"]:
                    raise AssertionError("Stop recovery diagnostic at first failed run")
    result["summary"] = summarize(result["runs"])
finally:
    result["daemon_cleanup"] = adapter.stop_daemon(pid)
    (HERE / "recovery-diagnostic-results.json").write_text(json.dumps(result, indent=2) + "\n")
print("RECOVERY_SUMMARY", json.dumps(result.get("summary")), flush=True)
