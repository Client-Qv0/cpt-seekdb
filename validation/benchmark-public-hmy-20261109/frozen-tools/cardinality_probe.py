#!/usr/bin/env python3
"""Bounded, real-cgroup cardinality diagnostics; not an official benchmark.

Requires Linux, Docker and root access to the container's host cgroup.  Driver
memory is outside the database's cgroup.  Import ContainerDatabase for matched
candidate runs.  No SQL results or resource observations are synthesized.
"""

import argparse
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import select
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
import traceback
import uuid

IMAGE = "sha256:27ea1213ba52ad529ba46eee11bd694b0a0a10cf36c2f9a6415f5f985376b6ef"
SOCKET = "unix:///var/tmp/minivectordb-docker/docker.sock"
MEMORY = 128 * 1024 * 1024
DAEMON = Path("/var/tmp/minivectordb-docker")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def docker(*args, socket=SOCKET, check=True, timeout=20):
    env = dict(os.environ, DOCKER_HOST=socket)
    return subprocess.run(["docker", *args], env=env, capture_output=True,
                          text=True, check=check, timeout=timeout)


def start_daemon():
    """Start only this task's dedicated daemon; return PID iff we started it."""
    if docker("info", check=False, timeout=5).returncode == 0:
        return None
    DAEMON.mkdir(parents=True, exist_ok=True)
    config = DAEMON / "daemon.json"
    config.write_text('{"features":{"containerd-snapshotter":false}}\n')
    command = ["dockerd", "--config-file", str(config),
               "--data-root", str(DAEMON / "data"),
               "--exec-root", str(DAEMON / "exec"),
               "--pidfile", str(DAEMON / "dockerd.pid"), "--host", SOCKET,
               "--bridge=none", "--iptables=false", "--ip6tables=false",
               "--ip-forward=false", "--ip-masq=false", "--storage-driver=vfs"]
    with (DAEMON / "dockerd.log").open("ab") as log:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=log, start_new_session=True)
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError("Task dockerd exited; inspect its retained log")
        if docker("info", check=False, timeout=5).returncode == 0:
            return proc.pid
        time.sleep(.1)
    raise RuntimeError("Task dockerd startup timed out")


def stop_daemon(pid):
    if pid is None:
        return {"stopped": False, "reason": "reused pre-existing task daemon"}
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.exists():
        command = cmdline.read_bytes()
        if str(DAEMON / "dockerd.pid").encode() not in command:
            raise RuntimeError("Refusing to stop unrelated process")
        import signal
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            state = Path(f"/proc/{pid}/stat")
            if not state.exists() or state.read_text().split()[2] == "Z":
                break
            time.sleep(.1)
    return {"stopped": True, "pid": pid, "cache_preserved": True}


class ContainerDatabase:
    """128MiB/2CPU/no-swap DB process. query() is SQL send-to-response wall time.

    capture() is explicit synchronous sampling outside a caller's timer; the
    background 100ms sampler runs throughout and its overhead is not subtracted.
    Constructor only waits for the container PID, not database recovery/readiness.
    A caller must time a real query to measure completed recovery. close() retains
    last live counters and Docker OOMKilled even if the cgroup disappears.
    """
    def __init__(self, binary, data_dir, image=IMAGE, socket=SOCKET, label="probe", cpuset=None,
                 image_binary=None):
        started = time.monotonic()
        self.binary = Path(binary).resolve()
        self.directory = Path(data_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.socket = socket
        self.name = "mvdb-cardinality-" + uuid.uuid4().hex
        self.stage = "startup"
        self.cg = None
        self.pid = None
        self.thread = None
        self.closed = False
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.pending = bytearray()
        self.stderr = tempfile.TemporaryFile(mode="w+b")
        self.record = {"label": label, "name": self.name, "binary": str(self.binary),
                       "binary_sha256": sha256(self.binary), "image_id": image,
                       "data_directory": str(self.directory), "snapshots": [],
                       "samples": [], "sample_errors": [], "requested_kill": False,
                       "sampler_period_seconds": .1, "query_count": 0,
                       "requested_cpuset": cpuset}
        args = ["docker", "run", "--name", self.name, "-i", "--network", "none",
                "--cpus", "2", "--memory", "128m", "--memory-swap", "128m",
                "--mount", f"type=bind,src={self.directory},dst=/data"]
        if image_binary is None:
            args += ["--mount", f"type=bind,src={self.binary},dst=/probe/minivectordb,readonly"]
        args += ["--entrypoint", image_binary or "/probe/minivectordb", image,
                "--data-dir", "/data", "--dev-protocol"]
        if cpuset is not None:
            args[2:2] = ["--cpuset-cpus", str(cpuset)]
        self.record["command"] = args
        self.proc = subprocess.Popen(args, env=dict(os.environ, DOCKER_HOST=socket),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.stderr, bufsize=0)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                found = docker("inspect", self.name, socket=socket, check=False)
                if found.returncode == 0:
                    info = json.loads(found.stdout)[0]
                    if info["State"]["Pid"]:
                        self.pid = info["State"]["Pid"]
                        relative = Path(f"/proc/{self.pid}/cgroup").read_text().strip().split(":", 2)[2]
                        self.cg = Path("/sys/fs/cgroup") / relative.lstrip("/")
                        self.record.update({"id": info["Id"], "image_id": info["Image"],
                                            "host_pid": self.pid, "cgroup_path": str(self.cg),
                                            "host_config": {k: info["HostConfig"][k] for k in
                                                            ("Memory", "MemorySwap", "NanoCpus", "NetworkMode", "CpusetCpus")}})
                        self.record["data_device"] = subprocess.check_output(
                            ["findmnt", "--noheadings", "--output", "SOURCE,MAJ:MIN,FSTYPE",
                             "--target", str(self.directory)], text=True).strip()
                        sample = self.capture("container_started")
                        if (not sample or sample["memory.max"] != str(MEMORY)
                                or sample["memory.swap.max"] != "0"
                                or sample["cpu.max"] != "200000 100000"):
                            raise RuntimeError("Actual cgroup limits do not match requested limits")
                        os.set_blocking(self.proc.stdin.fileno(), False)
                        os.set_blocking(self.proc.stdout.fileno(), False)
                        self.thread = threading.Thread(target=self._monitor, daemon=True)
                        self.thread.start()
                        self.record["constructor_seconds"] = time.monotonic() - started
                        return
                if self.proc.poll() is not None:
                    break
                time.sleep(.025)
            raise RuntimeError("Container did not reach running state: " + self.diagnostics())
        except BaseException:
            self.close(kill=True)
            raise

    def diagnostics(self):
        self.stderr.seek(0)
        return self.stderr.read().decode("utf-8", errors="replace")[-5000:]

    def _snapshot(self):
        if self.cg is None:
            return None
        value = {"monotonic": time.monotonic(), "stage": self.stage}
        for name in ("memory.current", "memory.peak", "memory.stat", "memory.events",
                     "memory.pressure", "memory.max", "memory.swap.max", "cpu.max", "cpuset.cpus.effective", "io.stat"):
            try:
                value[name] = (self.cg / name).read_text().strip()
            except OSError as error:
                value[name + "_error"] = str(error)
        try:
            status = Path(f"/proc/{self.pid}/status").read_text().splitlines()
            value["process_memory_auxiliary"] = {
                line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in status
                if line.startswith(("VmRSS:", "VmHWM:", "RssAnon:", "RssFile:", "RssShmem:"))}
        except OSError as error:
            value["process_status_error"] = str(error)
        if "memory.current" not in value:
            with self.lock:
                if len(self.record["sample_errors"]) < 5:
                    self.record["sample_errors"].append(value)
            return None
        with self.lock:
            self.record["last_live_snapshot"] = value
        return value

    def _monitor(self):
        while not self.stop.wait(.1):
            sample = self._snapshot()
            if sample:
                with self.lock:
                    self.record["samples"].append(sample)

    def capture(self, label):
        self.stage = label
        sample = self._snapshot()
        if sample:
            with self.lock:
                self.record["snapshots"].append({"label": label, "values": sample})
        return sample

    def query(self, sql, timeout=60):
        if "\n" in sql:
            raise ValueError("Only one-line SQL is supported by the development adapter")
        deadline = time.monotonic() + timeout
        data = memoryview((sql + "\n").encode())
        try:
            while data:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("SQL send deadline exceeded")
                _, ready, _ = select.select([], [self.proc.stdin], [], min(remaining, 1))
                if ready:
                    try:
                        sent = os.write(self.proc.stdin.fileno(), data)
                        data = data[sent:]
                    except BlockingIOError:
                        pass
            while b"\n" not in self.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("SQL response deadline exceeded")
                ready, _, _ = select.select([self.proc.stdout], [], [], min(remaining, 1))
                if ready:
                    chunk = os.read(self.proc.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError("Database closed stdout: " + self.diagnostics())
                    self.pending.extend(chunk)
                elif self.proc.poll() is not None:
                    raise RuntimeError("Database process exited: " + self.diagnostics())
            line, _, tail = self.pending.partition(b"\n")
            self.pending = bytearray(tail)
            result = json.loads(line)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise AssertionError(f"SQL failed: {sql[:160]}: {result}")
            self.record["query_count"] += 1
            return result
        except BaseException as error:
            self.record["last_query_failure"] = {"type": type(error).__name__, "message": str(error),
                                                  "sql_prefix": sql[:500], "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()}
            self.capture("query_failed")
            raise

    def close(self, kill=False, timeout=15):
        if self.closed:
            return
        self.capture("before_cleanup")
        self.record["requested_kill"] = kill
        if self.proc.poll() is None:
            if kill:
                docker("kill", "--signal", "KILL", self.name, socket=self.socket, check=False)
            elif self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.record["cleanup_timeout"] = True
                docker("kill", "--signal", "KILL", self.name, socket=self.socket, check=False)
                self.proc.wait(timeout=5)
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        found = docker("inspect", self.name, socket=self.socket, check=False)
        if found.returncode == 0:
            state = json.loads(found.stdout)[0]["State"]
            self.record["docker_final_state"] = {k: state.get(k) for k in
                ("Status", "Running", "OOMKilled", "ExitCode", "Error", "StartedAt", "FinishedAt")}
        self.record["stderr_tail"] = self.diagnostics()
        docker("rm", "--force", self.name, socket=self.socket, check=False)
        for stream in (self.proc.stdin, self.proc.stdout, self.stderr):
            if stream and not stream.closed:
                stream.close()
        self.closed = True


def rows(result):
    if not isinstance(result.get("rows"), list):
        raise AssertionError("Response lacks result rows")
    return result["rows"]


def compact(sample):
    if not sample:
        return None
    stat = dict(line.split() for line in sample["memory.stat"].splitlines())
    return {"current": int(sample["memory.current"]), "peak": int(sample["memory.peak"]),
            "anon": int(stat.get("anon", 0)), "file": int(stat.get("file", 0)),
            "events": sample["memory.events"], "pressure": sample.get("memory.pressure"),
            "rss_auxiliary": sample.get("process_memory_auxiliary")}


def row_values(key, kind):
    prefix = f"({key},{key % 97}"
    if kind == "vector4":
        prefix += f",'[{key % 31},{key % 17},{key % 7},{key % 3}]'"
    return prefix + ")"


class Case:
    def __init__(self, args, kind, count, directory):
        self.args, self.kind, self.count, self.directory = args, kind, count, directory
        # Independent scalar Python FP64 reference; outside all measured stages
        # and before any database container exists. Integers are exactly FP32.
        oracle_start = time.monotonic()
        self.vector_expected = None
        if kind == "vector4":
            self.vector_expected = heapq.nsmallest(8,
                ((math.sqrt((key % 31 - .5) ** 2 + (key % 17 - 1.5) ** 2
                            + (key % 7 - 2.5) ** 2 + (key % 3 - 1.) ** 2), key)
                 for key in range(count) if key % 97 >= 47))
        self.start = time.monotonic()
        self.deadline = self.start + args.case_seconds
        self.db = None
        self.phase_deadline = self.deadline
        self.record = {"kind": kind, "rows": count, "row_layout":
                       "BIGINT id + BIGINT x" + (" + VECTOR(4) FP32" if kind == "vector4" else ""),
                       "raw_fixed_field_bytes": 32 if kind == "vector4" else 16,
                       "write_batch_rows": args.batch_rows, "write_transaction": "autocommit one INSERT per batch",
                       "explicit_transaction_update_rows": min(count, args.transaction_rows),
                       "generation": {"random_seed": None, "id_order": "ascending 0..N-1",
                                      "x": "id modulo 97", "vector": "[id%31,id%17,id%7,id%3]"},
                       "oracle_seconds_excluded_from_case": self.start - oracle_start,
                       "phases": [], "containers": [], "passed": False,
                       "stage_seconds_limit": args.stage_seconds, "case_seconds_limit": args.case_seconds}

    def query(self, sql):
        remaining = min(self.phase_deadline, self.deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Stage/case time budget exhausted")
        return self.db.query(sql, timeout=remaining)

    def stage(self, label, operation):
        self.phase_deadline = min(self.deadline, time.monotonic() + self.args.stage_seconds)
        phase = {"name": label, "before": compact(self.db.capture(label + ":before")) if self.db else None}
        self.record["phases"].append(phase)
        started = time.monotonic()
        try:
            value = operation()
            phase.update({"passed": True, "detail": value})
        except BaseException as error:
            phase.update({"passed": False, "error": str(error), "error_type": type(error).__name__})
            raise
        finally:
            phase["elapsed_seconds"] = time.monotonic() - started
            phase["after"] = compact(self.db.capture(label + ":after")) if self.db else None
            print(json.dumps({"kind": self.kind, "N": self.count, "stage": label,
                              "seconds": phase["elapsed_seconds"], "passed": phase.get("passed"),
                              "memory": phase["after"]}), flush=True)

    def open(self, binary=None, label="main"):
        self.db = ContainerDatabase(binary or self.args.binary, self.directory,
                                    self.args.image, self.args.socket, label, self.args.cpuset)
        self.record["containers"].append(self.db.record)

    def pk_checks(self):
        keys = sorted({0, self.count - 1, self.count // 2, *[i * (self.count - 1) // 31 for i in range(32)]})
        for key in keys:
            actual = rows(self.query(f"SELECT id,x FROM items WHERE id={key};"))
            if actual != [[key, key % 97]]:
                raise AssertionError(f"PK mismatch for {key}: {actual}")
        return {"point_queries": len(keys), "rows_verified": len(keys)}

    def scan(self):
        actual = rows(self.query("SELECT id,x FROM items WHERE x>=0 ORDER BY x DESC,id ASC LIMIT 8;"))
        expected = [[96 + i * 97, 96] for i in range(8)]
        if actual != expected:
            raise AssertionError(f"Full scan mismatch: {actual}")
        return {"result_rows": 8, "scanned_domain_rows": self.count,
                "cache_state": "may populate bounded decoded-row cache; no diagnostic disable switch"}

    def vector_topk(self):
        actual = rows(self.query("SELECT id,L2_DISTANCE(v,'[0.5,1.5,2.5,1]') AS d FROM items WHERE x>=47 ORDER BY d,id LIMIT 8;"))
        if len(actual) != 8:
            raise AssertionError("Vector TopK row count mismatch")
        for (actual_id, distance), (expected_distance, expected_id) in zip(actual, self.vector_expected):
            if actual_id != expected_id or not math.isclose(distance, expected_distance, rel_tol=1e-12, abs_tol=1e-12):
                raise AssertionError(f"Independent vector TopK mismatch: {actual}")
        return {"result_rows": 8, "filtered_domain": "x>=47", "recall": 1.0,
                "reference": "independent Python FP64 exhaustive filtered distance and (distance,id) order",
                "expected": [[key, dist] for dist, key in self.vector_expected]}

    def run(self):
        try:
            self.open()
            extra = ",v VECTOR(4)" if self.kind == "vector4" else ""
            self.stage("create", lambda: self.query(f"CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT{extra});"))
            def write():
                total = 0
                for first in range(0, self.count, self.args.batch_rows):
                    end = min(self.count, first + self.args.batch_rows)
                    self.query("INSERT INTO items VALUES " + ",".join(row_values(k, self.kind) for k in range(first, end)) + ";")
                    total = end
                    self.record["acknowledged_insert_rows"] = total
                return {"acknowledged_rows": total}
            self.stage("write", write)
            self.stage("pk_lookup", self.pk_checks)
            self.stage("scan_first", self.scan)
            self.stage("scan_warm", lambda: [self.scan() for _ in range(3)])
            if self.kind == "vector4":
                self.stage("vector_topk", self.vector_topk)
            def invalidate():
                self.query("UPDATE items SET x=999 WHERE id=0;")
                if rows(self.query("SELECT x FROM items WHERE id=0;")) != [[999]]:
                    raise AssertionError("UPDATE result mismatch")
                return {"affected_rows": 1, "cache_state": "invalidated by mutation; allocator may retain pages"}
            self.stage("update_cache_invalidation", invalidate)
            self.stage("restore_update", lambda: self.query("UPDATE items SET x=0 WHERE id=0;"))
            self.stage("scan_after_invalidation", self.scan)
            def deletion():
                self.query("DELETE FROM items WHERE id<100;")
                if rows(self.query("SELECT id FROM items WHERE id<100 LIMIT 1;")):
                    raise AssertionError("DELETE did not remove rows")
                self.query("INSERT INTO items VALUES " + ",".join(row_values(k, self.kind) for k in range(100)) + ";")
                return {"deleted_and_reinserted_rows": 100}
            self.stage("delete_restore", deletion)
            def transaction():
                count = min(self.count, self.args.transaction_rows)
                self.query("BEGIN;")
                self.query(f"UPDATE items SET x=777 WHERE id<{count};")
                self.db.capture("transaction_pending_map")
                if rows(self.query("SELECT x FROM items WHERE id=0;")) != [[777]]:
                    raise AssertionError("Pending transaction not visible")
                self.query("ROLLBACK;")
                if rows(self.query("SELECT x FROM items WHERE id=0;")) != [[0]]:
                    raise AssertionError("Rollback mismatch")
                self.query("BEGIN;")
                self.query("UPDATE items SET x=666 WHERE id=0;")
                self.query("COMMIT;")
                if rows(self.query("SELECT x FROM items WHERE id=0;")) != [[666]]:
                    raise AssertionError("Commit mismatch")
                self.query("UPDATE items SET x=0 WHERE id=0;")
                return {"rollback_update_rows": count, "commit_update_rows": 1}
            self.stage("transaction", transaction)
            if self.args.checkpoint_helper:
                self.db.close()
                self.db = None
                def checkpoint():
                    self.open(self.args.checkpoint_helper, "Store-only checkpoint helper")
                    recovery_start = time.monotonic()
                    ready = self.query("READY")
                    recovery_seconds = time.monotonic() - recovery_start
                    self.db.capture("checkpoint_after_recovery")
                    checkpoint_start = time.monotonic()
                    done = self.query("CHECKPOINT")
                    checkpoint_seconds = time.monotonic() - checkpoint_start
                    return {"ready": ready, "checkpoint": done,
                            "ready_query_seconds": recovery_seconds,
                            "checkpoint_query_seconds": checkpoint_seconds,
                            "scope": "separately hashed diagnostic binary using same frozen storage.cpp; includes recovery"}
                self.stage("checkpoint_helper", checkpoint)
            self.db.close(kill=True)
            self.db = None
            def restart():
                self.open(label="production restart")
                return self.pk_checks()
            self.stage("restart_recovery", restart)
            self.stage("scan_after_recovery", self.scan)
            self.record["passed"] = True
        except BaseException as error:
            self.record["error"] = {"type": type(error).__name__, "message": str(error),
                                    "traceback": traceback.format_exc()}
        finally:
            if self.db:
                self.db.close(kill=not self.record["passed"])
            self.record["elapsed_seconds"] = time.monotonic() - self.start
        return self.record

    def run_transaction_probe(self, transaction_sizes):
        """Separate bounded pending-map experiment; fresh recovery for each size.

        No full scan occurs before BEGIN, so decoded-cache retention does not
        contaminate this comparison. The allocator may retain pending-map pages
        after ROLLBACK; the next size uses a new process to avoid that history.
        """
        self.record["mode"] = "transaction_pending_map_probe"
        self.record["transaction_sizes"] = transaction_sizes
        try:
            self.open(label="transaction probe dataset setup")
            extra = ",v VECTOR(4)" if self.kind == "vector4" else ""
            self.stage("create", lambda: self.query(f"CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT{extra});"))
            def write():
                for first in range(0, self.count, self.args.batch_rows):
                    end = min(self.count, first + self.args.batch_rows)
                    self.query("INSERT INTO items VALUES " + ",".join(row_values(k, self.kind) for k in range(first, end)) + ";")
                    self.record["acknowledged_insert_rows"] = end
                return {"acknowledged_rows": self.count}
            self.stage("write", write)
            self.db.close()
            self.db = None
            for pending_count in transaction_sizes:
                def recover():
                    self.open(label=f"fresh recovery for transaction {pending_count}")
                    return self.pk_checks()
                self.stage(f"tx_{pending_count}_recovery", recover)
                def pending():
                    self.query("BEGIN;")
                    self.query(f"UPDATE items SET x=777 WHERE id<{pending_count};")
                    pending_state = compact(self.db.capture(f"tx_{pending_count}_pending"))
                    for key in (0, pending_count - 1):
                        if rows(self.query(f"SELECT x FROM items WHERE id={key};")) != [[777]]:
                            raise AssertionError("Pending transaction boundary mismatch")
                    if pending_count < self.count:
                        if rows(self.query(f"SELECT x FROM items WHERE id={pending_count};")) != [[pending_count % 97]]:
                            raise AssertionError("Transaction modified out-of-range row")
                    self.query("ROLLBACK;")
                    for key in (0, pending_count - 1):
                        if rows(self.query(f"SELECT x FROM items WHERE id={key};")) != [[key % 97]]:
                            raise AssertionError("Rollback boundary mismatch")
                    return {"pending_rows": pending_count, "pending_memory": pending_state,
                            "cache_state": "empty after fresh process recovery; no full SELECT scan before BEGIN",
                            "verification": "transaction-visible boundary rows and restored original values after rollback"}
                self.stage(f"tx_{pending_count}_update_rollback", pending)
                self.db.close()
                self.db = None
            self.record["passed"] = True
        except BaseException as error:
            self.record["error"] = {"type": type(error).__name__, "message": str(error),
                                    "traceback": traceback.format_exc()}
        finally:
            if self.db:
                self.db.close(kill=not self.record["passed"])
            self.record["elapsed_seconds"] = time.monotonic() - self.start
        return self.record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--checkpoint-helper", type=Path)
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--socket", default=SOCKET)
    parser.add_argument("--cpuset", help="Optional fixed host CPU IDs; default retains quota-only baseline configuration")
    parser.add_argument("--sizes", default="50000,100000,250000,500000,1000000,2000000")
    parser.add_argument("--kinds", default="scalar,vector4")
    parser.add_argument("--batch-rows", type=int, default=1000)
    parser.add_argument("--transaction-rows", type=int, default=25000)
    parser.add_argument("--transaction-sizes", help="Separate pending-map probe, e.g. 25000,100000,250000; no regular scan/checkpoint stages")
    parser.add_argument("--stage-seconds", type=float, default=60)
    parser.add_argument("--case-seconds", type=float, default=180)
    parser.add_argument("--degradation-factor", type=float, default=3)
    parser.add_argument("--manage-daemon", action="store_true")
    parser.add_argument("--retain-data", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sizes = [int(n) for n in args.sizes.split(",")]
    if any(n < 1000 or n > 2000000 for n in sizes):
        parser.error("Sizes must be between 1000 and the bounded cap 2,000,000")
    transaction_sizes = [int(n) for n in args.transaction_sizes.split(",")] if args.transaction_sizes else None
    if transaction_sizes and any(n < 1 or n > min(250000, min(sizes)) for n in transaction_sizes):
        parser.error("Transaction sizes must be positive and <= min(250000, smallest dataset)")
    result = {"tool_sha256": sha256(__file__), "binary_sha256": sha256(args.binary),
              "binary": str(args.binary.resolve()), "source_manifest_sha256": sha256(args.source_manifest) if args.source_manifest else None,
              "image_id": args.image, "memory_bytes": MEMORY, "swap_bytes": 0, "cpus": 2,
              "requested_cpuset": args.cpuset, "argv": list(os.sys.argv),
              "limits": {"stage_seconds": args.stage_seconds, "case_seconds": args.case_seconds,
                         "degradation_factor": args.degradation_factor, "maximum_rows": max(sizes)},
              "cases": [], "official_benchmark": False,
              "interpretation": ["memory.peak reaching the cap is not proof of a leak; compare anon/file/current snapshots.",
                                 "Decoded cache, allocator retention, key-offset mapping, sort and transaction memory may coexist.",
                                 "Raw io.stat on shared WSL device is uncalibrated; do not derive formal score or physical attribution.",
                                 "Stop expanding each schema on its first failure or >3x normalized write/scan regression.",
                                 "Short-record recovery is sampled by PK plus an independently expected full-domain TopK scan, not a full data dump."]}
    if args.checkpoint_helper:
        result["checkpoint_helper_sha256"] = sha256(args.checkpoint_helper)
    daemon_pid = None
    try:
        if args.manage_daemon:
            daemon_pid = start_daemon()
        for kind in args.kinds.split(","):
            if kind not in ("scalar", "vector4"):
                raise ValueError("Unknown row kind")
            baseline_rates = {}
            for count in sizes:
                directory = Path(tempfile.mkdtemp(prefix=f"mvdb-cardinality-{kind}-{count}-", dir="/var/tmp"))
                runner = Case(args, kind, count, directory)
                case = runner.run_transaction_probe(transaction_sizes) if transaction_sizes else runner.run()
                result["cases"].append(case)
                for phase in case["phases"]:
                    if phase["name"] in ("write", "scan_first") and phase.get("passed"):
                        normalized = phase["elapsed_seconds"] / count
                        phase["seconds_per_input_row"] = normalized
                        reference = baseline_rates.setdefault(phase["name"], normalized)
                        if normalized > reference * args.degradation_factor:
                            case.setdefault("degradation_stop", []).append({"phase": phase["name"],
                                "normalized_ratio_to_first_size": normalized / reference})
                if not args.retain_data and case["passed"]:
                    shutil.rmtree(directory)
                    case["data_cleaned"] = True
                else:
                    case["data_retained"] = str(directory)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
                print("CASE", json.dumps({"kind": kind, "N": count, "passed": case["passed"],
                                             "seconds": case["elapsed_seconds"],
                                             "error": case.get("error", {}).get("message"),
                                             "degradation_stop": case.get("degradation_stop")}), flush=True)
                if not case["passed"] or case.get("degradation_stop"):
                    break
    finally:
        result["daemon_cleanup"] = stop_daemon(daemon_pid) if args.manage_daemon else {"managed": False}
        args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
