#!/usr/bin/env python3
"""Formal-JSONL paired benchmark for equality-filter code blocks.

This runner measures complete request/response calls. It does not change the
official workload or claim official scoring. Each database is started in a
fresh 200%-CPU / 2-GiB / swap-off user cgroup scope.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import select
import statistics
import subprocess
import time
import uuid


ROWS = 10000
DIMENSION = 128
QUERY_COUNT = 1000
BATCH_SIZE = 100
TOP_K = 10
SEEDS = (3179, 3181, 3187)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def generate_workload(seed):
    rng = random.Random(seed)
    writes = []
    for begin in range(0, ROWS, BATCH_SIZE):
        tuples = []
        for row in range(begin, min(begin + BATCH_SIZE, ROWS)):
            vector = json.dumps(
                [round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)],
                separators=(",", ":"),
            )
            tuples.append(f"({row},'g{row % 5}','{vector}')")
        writes.append("INSERT INTO bench VALUES " + ",".join(tuples) + ";")
    queries = []
    filtered = []
    for index in range(QUERY_COUNT):
        vector = json.dumps(
            [round(rng.uniform(-1, 1), 6) for _ in range(DIMENSION)],
            separators=(",", ":"),
        )
        is_filtered = bool(index % 2)
        where = f" WHERE grp='g{index % 5}'" if is_filtered else ""
        queries.append(
            f"SELECT id,L2_DISTANCE(v,'{vector}') AS d FROM bench{where} "
            f"ORDER BY d LIMIT {TOP_K};"
        )
        filtered.append(is_filtered)
    digest = hashlib.sha256()
    for statement in writes + queries:
        digest.update(statement.encode("utf-8"))
        digest.update(b"\n")
    return {
        "seed": seed,
        "rows": ROWS,
        "dimension": DIMENSION,
        "query_count": QUERY_COUNT,
        "batch_size": BATCH_SIZE,
        "top_k": TOP_K,
        "writes": writes,
        "queries": queries,
        "filtered": filtered,
        "sql_sha256": digest.hexdigest(),
    }


class Session:
    def __init__(self, binary, directory):
        self.binary = str(Path(binary).resolve())
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.stderr = self.directory.parent / "stderr.log"
        self.stderr_stream = open(self.stderr, "wb")
        command = [self.binary, "--data-dir", str(self.directory)]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_stream,
            bufsize=0,
        )
        self.buffer = b""
        self.sequence = 0
        ready = self.line(timeout=30)
        if ready != {"type": "ready"}:
            raise RuntimeError(f"invalid ready message: {ready!r}")

    def line(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("JSONL response timeout")
            readable, _, _ = select.select(
                [self.process.stdout], [], [], min(remaining, 1)
            )
            if not readable:
                continue
            chunk = self.process.stdout.read(65536)
            if not chunk:
                raise RuntimeError(
                    f"database closed stdout with exit {self.process.poll()}"
                )
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(raw)

    def request(self, sql=None, op="execute", timeout=120):
        self.sequence += 1
        identity = self.sequence
        request = {"id": identity, "op": op}
        if sql is not None:
            request.update(sql=sql, search_mode="exact")
        raw = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        self.process.stdin.write(raw + b"\n")
        self.process.stdin.flush()
        response = self.line(timeout)
        if response.get("id") != identity or response.get("ok") is not True:
            raise RuntimeError(f"request {identity} failed: {response!r}")
        return response

    def close(self):
        self.request(op="shutdown")
        self.process.stdin.close()
        code = self.process.wait(timeout=30)
        extra = self.process.stdout.read()
        self.process.stdout.close()
        self.stderr_stream.close()
        if code != 0 or extra:
            raise RuntimeError(
                f"database shutdown failed: exit={code}, extra_stdout={extra!r}"
            )


def cgroup_snapshot():
    cgroup = Path("/proc/self/cgroup").read_text().strip().split(":", 2)[2]
    root = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
    result = {"cgroup": cgroup}
    for name in (
        "cpu.max",
        "cpu.stat",
        "memory.max",
        "memory.swap.max",
        "memory.current",
        "memory.peak",
        "memory.stat",
        "memory.events",
        "io.stat",
    ):
        path = root / name
        result[name] = path.read_text() if path.exists() else None
    return result


def process_snapshot(pid):
    status_path = Path(f"/proc/{pid}/status")
    result = {"status": None, "cpu_ticks": None}
    if status_path.exists():
        status = status_path.read_text()
        result["status"] = {
            key: next(
                (line.split(None, 1)[1].strip() for line in status.splitlines()
                 if line.startswith(key + ":")),
                None,
            )
            for key in ("VmHWM", "VmRSS", "Threads")
        }
    stat_path = Path(f"/proc/{pid}/stat")
    if stat_path.exists():
        fields = stat_path.read_text().split()
        result["cpu_ticks"] = int(fields[13]) + int(fields[14])
    return result


def summarize(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return {
        "count": len(ordered),
        "sum": sum(ordered),
        "mean": statistics.mean(ordered),
        "median": statistics.median(ordered),
        "p95": p95,
        "min": ordered[0],
        "max": ordered[-1],
    }


def run_worker(args):
    run_dir = Path(args.output_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    workload = generate_workload(args.seed)
    before_binary = sha256_file(args.binary)
    result = {
        "variant": args.variant,
        "binary": str(Path(args.binary).resolve()),
        "binary_sha256_before": before_binary,
        "seed": args.seed,
        "workload": {key: workload[key] for key in (
            "seed", "rows", "dimension", "query_count",
            "batch_size", "top_k", "sql_sha256"
        )},
        "limits": cgroup_snapshot(),
        "failure": None,
    }
    session = None
    try:
        session = Session(args.binary, run_dir / "data")
        session.request(
            "CREATE TABLE bench "
            "(id BIGINT PRIMARY KEY,grp VARCHAR(8),v VECTOR(128));"
        )
        start = time.perf_counter()
        for statement in workload["writes"]:
            response = session.request(statement)
            if response.get("affected_rows") != BATCH_SIZE:
                raise RuntimeError(f"write acknowledgement mismatch: {response!r}")
        result["write_seconds"] = time.perf_counter() - start

        warmup = []
        for index, statement in enumerate(workload["queries"][:10]):
            start = time.perf_counter_ns()
            session.request(statement)
            warmup.append((time.perf_counter_ns() - start) / 1e9)
        result["warmup_seconds"] = summarize(warmup)

        pass_timings = []
        first_response_hashes = None
        for pass_index in range(args.passes):
            filtered_seconds = 0.0
            unfiltered_seconds = 0.0
            response_hashes = []
            for statement, filtered in zip(
                workload["queries"], workload["filtered"]
            ):
                start = time.perf_counter_ns()
                response = session.request(statement)
                elapsed = (time.perf_counter_ns() - start) / 1e9
                if filtered:
                    filtered_seconds += elapsed
                else:
                    unfiltered_seconds += elapsed
                if len(response.get("rows", [])) != TOP_K:
                    raise RuntimeError("TopK response count mismatch")
                canonical = json.dumps(
                    response["rows"], ensure_ascii=False, separators=(",", ":")
                ).encode()
                response_hashes.append(hashlib.sha256(canonical).hexdigest())
            if first_response_hashes is None:
                first_response_hashes = response_hashes
            elif response_hashes != first_response_hashes:
                raise RuntimeError("repeated query set returned different rows")
            pass_timings.append({
                "filtered_seconds": filtered_seconds,
                "unfiltered_seconds": unfiltered_seconds,
                "total_queries_seconds": filtered_seconds + unfiltered_seconds,
            })
        result["query_passes"] = pass_timings
        result["timings"] = {
            key: summarize([entry[key] for entry in pass_timings])
            for key in (
                "filtered_seconds", "unfiltered_seconds", "total_queries_seconds"
            )
        }
        result["total_queries_seconds"] = result["timings"][
            "total_queries_seconds"
        ]["median"]
        result["response_sequence_sha256"] = hashlib.sha256(
            ("\n".join(first_response_hashes) + "\n").encode()
        ).hexdigest()
        result["process_after_queries"] = process_snapshot(session.process.pid)
        session.close()
        session = None
    except Exception as error:
        result["failure"] = f"{type(error).__name__}: {error}"
    finally:
        if session is not None:
            if session.process.poll() is None:
                session.process.kill()
                session.process.wait(timeout=10)
            if not session.process.stdout.closed:
                session.process.stdout.close()
            if not session.stderr_stream.closed:
                session.stderr_stream.close()

    result["cgroup_after_queries"] = cgroup_snapshot()
    result["binary_sha256_after"] = sha256_file(args.binary)
    result["binary_unchanged"] = (
        result["binary_sha256_after"] == result["binary_sha256_before"]
    )
    result["passed"] = result["failure"] is None and result["binary_unchanged"]
    write_json(run_dir / "run.json", result)
    return 0 if result["passed"] else 1


def launch_run(command, variant, binary, seed, run_dir, passes, cpuset):
    unit = "q7-" + uuid.uuid4().hex[:16]
    wrapper = [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "-p", "CPUQuota=200%",
        "-p", "MemoryMax=2G",
        "-p", "MemorySwapMax=0",
        command,
        "--worker",
        "--variant", variant,
        "--binary", str(Path(binary).resolve()),
        "--seed", str(seed),
        "--passes", str(passes),
        "--output-dir", str(run_dir.resolve()),
    ]
    if cpuset:
        wrapper = ["taskset", "-c", cpuset] + wrapper
    completed = subprocess.run(wrapper, text=True, capture_output=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(
            f"worker failed for {variant}: {completed.stderr or completed.stdout}"
        )


def summarize_experiment(runs):
    pair_groups = {}
    for run in runs:
        pair_groups.setdefault(run["pair_index"], {})[run["variant"]] = run
    pairs = []
    for pair_index in sorted(pair_groups):
        group = pair_groups[pair_index]
        baseline, candidate = group["baseline"], group["candidate"]
        passed = (
            baseline["passed"]
            and candidate["passed"]
            and baseline["response_sequence_sha256"]
            == candidate["response_sequence_sha256"]
        )
        entry = {"pair_index": pair_index, "passed": passed}
        for metric in ("total_queries_seconds",):
            entry[metric] = {
                "baseline": baseline[metric],
                "candidate": candidate[metric],
                "baseline_over_candidate": baseline[metric] / candidate[metric],
                "candidate_faster": candidate[metric] < baseline[metric],
            }
        for surface in ("filtered", "unfiltered"):
            base = baseline["timings"][surface + "_seconds"]["median"]
            cand = candidate["timings"][surface + "_seconds"]["median"]
            entry[surface + "_seconds"] = {
                "baseline": base,
                "candidate": cand,
                "baseline_over_candidate": base / cand,
                "candidate_faster": cand < base,
            }
        base_peak = int(
            baseline["cgroup_after_queries"]["memory.peak"].strip()
        )
        cand_peak = int(
            candidate["cgroup_after_queries"]["memory.peak"].strip()
        )
        entry["memory_peak_delta_bytes"] = cand_peak - base_peak
        entry["io_increase_claim"] = False
        pairs.append(entry)

    total_ratios = [
        pair["total_queries_seconds"]["baseline_over_candidate"]
        for pair in pairs if pair["passed"]
    ]
    filtered_ratios = [
        pair["filtered_seconds"]["baseline_over_candidate"]
        for pair in pairs if pair["passed"]
    ]
    unfiltered_ratios = [
        pair["unfiltered_seconds"]["baseline_over_candidate"]
        for pair in pairs if pair["passed"]
    ]
    return {
        "pairs": pairs,
        "valid_pairs": len(total_ratios),
        "all_pairs_correct": len(total_ratios) == len(pairs),
        "total_query_ratio": {
            "median": statistics.median(total_ratios) if total_ratios else None,
            "wins": sum(value > 1 for value in total_ratios),
            "count": len(total_ratios),
        },
        "filtered_ratio": {
            "median": statistics.median(filtered_ratios) if filtered_ratios else None,
            "wins": sum(value > 1 for value in filtered_ratios),
            "count": len(filtered_ratios),
        },
        "unfiltered_ratio": {
            "median": statistics.median(unfiltered_ratios) if unfiltered_ratios else None,
            "wins": sum(value > 1 for value in unfiltered_ratios),
            "count": len(unfiltered_ratios),
        },
        "max_memory_peak_delta_bytes": (
            max(pair["memory_peak_delta_bytes"] for pair in pairs)
            if pairs else None
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--variant", choices=("baseline", "candidate"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--pairs", type=int, default=20)
    parser.add_argument("--passes", type=int, default=10)
    parser.add_argument(
        "--cpuset",
        default="0,1",
        help="Pin the local comparison to two CPUs; pass empty for no pinning.",
    )
    args = parser.parse_args()
    if args.worker:
        if not all((args.variant, args.binary, args.seed, args.output_dir)):
            parser.error("worker needs variant, binary, seed and output-dir")
        return run_worker(args)
    if not args.baseline or not args.candidate or not args.output_dir:
        parser.error("orchestrator needs baseline, candidate and output-dir")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error(f"output directory is not empty: {output}")
    command = str(Path(__file__).resolve())
    runs = []
    for pair_index in range(args.pairs):
        order = (
            (("baseline", args.baseline), ("candidate", args.candidate))
            if pair_index % 2 == 0
            else (("candidate", args.candidate), ("baseline", args.baseline))
        )
        seed = SEEDS[pair_index % len(SEEDS)]
        for variant, binary in order:
            run_dir = output / f"pair-{pair_index + 1:02d}-{variant}"
            launch_run(
                command, variant, binary, seed, run_dir, args.passes, args.cpuset
            )
            result = json.loads((run_dir / "run.json").read_text())
            result["pair_index"] = pair_index
            runs.append(result)
            print(
                json.dumps(
                    {"pair": pair_index + 1, "variant": variant,
                     "passed": result["passed"]},
                    separators=(",", ":"),
                ),
                flush=True,
            )
    summary = summarize_experiment(runs)
    summary["scope"] = (
        "Local formal-JSONL paired evidence under a 200%-CPU, 2-GiB, "
        "swap-off cgroup; not official scoring."
    )
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_pairs_correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
