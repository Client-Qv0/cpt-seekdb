#!/usr/bin/env python3
"""Validate acknowledged batches and unfinished transaction after Docker SIGKILL."""
import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import selectors
import struct
import subprocess
import time
import uuid

ACTIVE = []


def f32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def docker(*args):
    return subprocess.run(["docker", *map(str, args)], capture_output=True, check=True, timeout=60)


class Session:
    def __init__(self, image, data, output, label):
        self.name = "mvdb-pin-recovery-" + uuid.uuid4().hex[:12]
        self.label = label
        self.sequence = 0
        self.buffer = b""
        self.trace = gzip.open(output / (label + "-trace.jsonl.gz"), "wt", encoding="utf8")
        self.stderr = (output / (label + "-stderr.txt")).open("wb")
        command = ["docker", "run", "--name", self.name, "-i", "--network", "none",
                   "--read-only", "--memory", "128m", "--memory-swap", "128m",
                   "--cpus", "2", "--pids-limit", "128", "--mount",
                   f"type=bind,src={data},dst=/data", image]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, bufsize=0)
        self.cleaned = False
        ACTIVE.append(self)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        if self.line() != {"type": "ready"}:
            raise AssertionError("invalid ready response")
        self.info = json.loads(docker("inspect", self.name).stdout)[0]
        pid = self.info["State"]["Pid"]
        if pid <= 0:
            raise RuntimeError("container is not running")
        lines = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
        rel = next(line[3:] for line in lines if line.startswith("0::"))
        self.cgroup = Path("/sys/fs/cgroup") / rel.lstrip("/")
        self.capture("ready")

    def line(self):
        deadline = time.monotonic() + 120
        while b"\n" not in self.buffer:
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise TimeoutError("container response timeout")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("container closed stdout")
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\n", 1)
        self.trace.write(json.dumps({"response_raw": raw.decode("utf8")}, ensure_ascii=False) + "\n")
        return json.loads(raw)

    def request(self, sql=None, op="execute"):
        self.sequence += 1
        req = {"id": self.sequence, "op": op}
        if sql is not None:
            req.update(sql=sql, search_mode="exact")
        raw = (json.dumps(req, separators=(",", ":")) + "\n").encode()
        self.trace.write(json.dumps({"request": req}, ensure_ascii=False) + "\n")
        remaining = memoryview(raw)
        while remaining:
            written = self.process.stdin.write(remaining)
            if not written:
                raise RuntimeError("container stdin closed during request")
            remaining = remaining[written:]
        self.process.stdin.flush()
        response = self.line()
        if response.get("id") != self.sequence or response.get("ok") is not True:
            raise AssertionError(response)
        return response

    def capture(self, label):
        names = ("memory.max", "memory.swap.max", "memory.peak", "memory.events", "cpu.max", "io.stat")
        snapshot = {name: (self.cgroup / name).read_text() for name in names}
        if snapshot["memory.max"].strip() != "134217728" or snapshot["memory.swap.max"].strip() != "0":
            raise AssertionError("container memory/swap limits do not match")
        if snapshot["cpu.max"].strip() != "200000 100000":
            raise AssertionError("container CPU quota does not match")
        events = dict(line.split() for line in snapshot["memory.events"].splitlines())
        if any(int(events[name]) for name in ("oom", "oom_kill")):
            raise AssertionError("container encountered an OOM")
        self.trace.write(json.dumps({"snapshot": label, "files": snapshot}) + "\n")
        return snapshot

    def finish(self, kill):
        snapshot = self.capture("before_kill" if kill else "before_shutdown")
        if kill:
            docker("kill", "--signal", "KILL", self.name)
        else:
            self.request(op="shutdown")
        self.process.stdin.close()
        exit_code = self.process.wait(timeout=30)
        after = json.loads(docker("inspect", self.name).stdout)[0]["State"]
        if kill and (exit_code != 137 or after["ExitCode"] != 137 or after["OOMKilled"]):
            raise AssertionError({"docker_cli": exit_code, "state": after})
        if not kill and (exit_code != 0 or after["ExitCode"] != 0):
            raise AssertionError({"docker_cli": exit_code, "state": after})
        self.selector.close()
        self.stderr.close()
        self.trace.close()
        docker("rm", "-v", self.name)
        self.cleaned = True
        return {"exit_code": exit_code, "oom_killed": after["OOMKilled"], "snapshot": snapshot}

    def abort(self):
        if self.cleaned:
            return
        try:
            docker("rm", "-f", "-v", self.name)
        except (subprocess.SubprocessError, OSError):
            pass
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=30)
        self.selector.close()
        self.stderr.close()
        self.trace.close()
        self.cleaned = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.data_root, args.output):
        if not path.is_absolute() or path.exists() or "," in str(path):
            parser.error("data-root and output must be new absolute paths without commas")
    if args.data_root == args.output or args.data_root in args.output.parents or args.output in args.data_root.parents:
        parser.error("data-root and output must be separate, non-nested paths")
    args.data_root.mkdir(parents=True)
    args.output.mkdir(parents=True)
    image_id = docker("image", "inspect", args.image, "--format", "{{.Id}}").stdout.decode().strip()
    rng = random.Random(20261110)
    rows, batches = [], []
    for start in range(0, 10000, 100):
        values = []
        for key in range(start, start + 100):
            vector = [f32(round(rng.uniform(-1, 1), 6)) for _ in range(128)]
            rows.append(vector)
            values.append(f"({key},'g{key % 5}','[" + ",".join(map(str, vector)) + "]')")
        batches.append("INSERT INTO crash_vectors VALUES " + ",".join(values) + ";")
    first = Session(image_id, args.data_root, args.output, "before")
    first.request("CREATE TABLE crash_vectors (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR(128));")
    for batch in batches:
        if first.request(batch).get("affected_rows") != 100:
            raise AssertionError("batch acknowledgement mismatch")
    first.request("BEGIN;")
    first.request("UPDATE crash_vectors SET grp='tx' WHERE id=0;")
    first.request("DELETE FROM crash_vectors WHERE id=1;")
    first.request("INSERT INTO crash_vectors VALUES (10000,'tx','[" + ",".join(["0"] * 128) + "]');")
    if first.request("SELECT id,grp FROM crash_vectors WHERE id<=1 ORDER BY id;")["rows"] != [[0, "tx"]]:
        raise AssertionError("uncommitted transaction not visible")
    killed = first.finish(kill=True)
    second = Session(image_id, args.data_root, args.output, "after")
    ids = second.request("SELECT id,grp FROM crash_vectors ORDER BY id;")["rows"]
    if ids != [[key, f"g{key % 5}"] for key in range(10000)]:
        raise AssertionError("record IDs/groups or rolled-back transaction differ")
    checked_components = 0
    for start in range(0, 10000, 100):
        actual = second.request(f"SELECT id,grp,v FROM crash_vectors WHERE id>={start} AND id<{start + 100} ORDER BY id;")["rows"]
        if len(actual) != 100:
            raise AssertionError("readback row count differs")
        for offset, (key, group, vector) in enumerate(actual):
            expected_id = start + offset
            if key != expected_id or group != f"g{key % 5}" or len(vector) != 128:
                raise AssertionError("readback row differs")
            for got, expected in zip(vector, rows[key]):
                if not math.isfinite(got) or struct.pack("!f", got) != struct.pack("!f", expected):
                    raise AssertionError(f"vector component differs for row {key}")
                checked_components += 1
    restarted = second.finish(kill=False)
    result = {"status": "PASS", "image_id": image_id, "seed": 20261110,
              "acknowledged_batches": len(batches), "readback_rows": len(ids),
              "checked_fp32_components": checked_components, "uncommitted_changes_rolled_back": True,
              "kill": killed, "restart": restarted,
              "scope": "actual default JSONL Docker entry; SIGKILL after all acknowledgements, not a power-failure test",
              "trace_sha256": {name: sha(args.output / (name + "-trace.jsonl.gz")) for name in ("before", "after")}}
    (args.output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "acknowledged_batches", "readback_rows", "checked_fp32_components", "uncommitted_changes_rolled_back")}))


if __name__ == "__main__":
    try:
        main()
    finally:
        for session in ACTIVE:
            session.abort()
