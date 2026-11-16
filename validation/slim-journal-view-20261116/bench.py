#!/usr/bin/env python3
"""Formal JSONL screening run. Run as root inside local Linux cgroup v2."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import select
import statistics
import subprocess
import tempfile
import time

CG = Path("/sys/fs/cgroup")
CREATE = "CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR(128));"

def workload(seed, count):
    rng = random.Random(seed)
    def vector():
        return json.dumps([round(rng.uniform(-1, 1), 6) for _ in range(128)], separators=(",", ":"))
    writes = ["INSERT INTO bench VALUES " + ",".join(
        f"({i},'g{i % 5}','{vector()}')" for i in range(b, b+100)) + ";"
        for b in range(0, 10000, 100)]
    queries = []
    for i in range(count):
        where = f" WHERE grp='g{i % 5}'" if i % 2 else ""
        queries.append(f"SELECT id,L2_DISTANCE(v,'{vector()}') AS d FROM bench{where} ORDER BY d LIMIT 10;")
    return writes, queries

def counters(path):
    return {name: (path/name).read_text().strip() for name in (
        "io.stat", "memory.peak", "memory.stat", "memory.events", "cpu.stat")}

def measure(binary, mode, data, writes, queries, write_only, cpus, mapped_proc=False):
    data.mkdir()
    cg = CG / ("mvdb-slim-" + data.parent.name + "-" + data.name)
    cg.mkdir()
    samples = {}
    proc = None
    try:
        for f, val in {"cpu.max": "200000 100000", "memory.max": str(2**31), "memory.swap.max": "0"}.items():
            (cg/f).write_text(val)
        samples["start"] = counters(cg)
        def enter():
            (cg/"cgroup.procs").write_text(str(os.getpid()))
            os.sched_setaffinity(0, cpus)
        env = dict(os.environ, MVDB_SLIM_PROBE=mode)
        with (data.parent/(data.name+".stderr")).open("w+") as err:
            proc = subprocess.Popen([str(binary), "--data-dir", str(data)],
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, preexec_fn=enter)
            def receive():
                if not select.select([proc.stdout], [], [], 30)[0]:
                    raise TimeoutError("JSONL read timed out")
                raw = proc.stdout.readline()
                if not raw:
                    err.seek(0)
                    raise RuntimeError(err.read())
                return raw
            assert json.loads(receive()) == {"type":"ready"}
            sequence = itertools.count()
            def request(sql=None):
                i = next(sequence)
                msg = {"id":i,"op":"shutdown"} if sql is None else {
                    "id":i,"op":"execute","sql":sql,"search_mode":"exact"}
                payload = (json.dumps(msg, separators=(",",":"))+"\n").encode()
                start = time.perf_counter_ns()
                proc.stdin.write(payload)
                proc.stdin.flush()
                raw = receive()
                elapsed = time.perf_counter_ns()-start
                result = json.loads(raw)
                assert result.get("id") == i and result.get("ok"), result
                return elapsed,raw,result
            request(CREATE)
            write = 0
            for sql in writes:
                ns,_,r = request(sql)
                assert r["affected_rows"] == 100
                write += ns
            samples["load"] = counters(cg)
            filtered, unfiltered = [], []
            digest = hashlib.sha256()
            prep = []
            if not write_only:
                for sql in queries[:10]:
                    prep.append(request(sql)[0])
                samples["prepared"] = counters(cg)
                if mode == "mapped" and mapped_proc:
                    maps = Path(f"/proc/{proc.pid}/maps").read_text()
                    actual = [line for line in maps.splitlines()
                              if line.endswith(str(data/"journal.mvdb"))]
                    assert actual and all(line.split()[1] == "r--p" for line in actual), actual
                    samples["journal_mapping"] = actual
                for i,sql in enumerate(queries):
                    ns,raw,r = request(sql)
                    assert len(r["rows"]) == 10
                    digest.update(raw)
                    (filtered if i%2 else unfiltered).append(ns)
                samples["queries"] = counters(cg)
            request()
            assert proc.wait(timeout=30) == 0
            # Journal was synced before each acknowledgment. Read counters while
            # the database cgroup still exists; the driver never enters it.
            samples["end"] = counters(cg)
            err.seek(0)
            stderr = err.read()
            if not write_only and not mapped_proc and mode in ("row", "mapped"):
                assert "SLIM_PROBE " + mode in stderr, "requested view never ran"
            assert "oom_kill 0" in samples["end"]["memory.events"]
            return dict(mode=mode, write_ns=write, preparation_ns=prep,
                filtered_ns=sum(filtered), unfiltered_ns=sum(unfiltered),
                output_sha256=digest.hexdigest(), samples=samples, stderr=stderr)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        cg.rmdir()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--control", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--modes", nargs="+", default=("base","row","mapped"))
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--queries", type=int, default=1000)
    p.add_argument("--cpus", default="0,2")
    p.add_argument("--driver-cpu", type=int)
    p.add_argument("--mapped-proc", action="store_true")
    p.add_argument("--write-only", action="store_true")
    a = p.parse_args()
    for ctl in ("cpu","io","memory"):
        if ctl not in (CG/"cgroup.subtree_control").read_text().split():
            (CG/"cgroup.subtree_control").write_text("+"+ctl)
    a.output.mkdir()
    (a.output/"environment.json").write_text(json.dumps({
        "args": vars(a), "kernel": os.uname().release,
        "tmp_device": [os.major(os.stat("/tmp").st_dev), os.minor(os.stat("/tmp").st_dev)],
        "binary_sha256": hashlib.sha256(a.binary.read_bytes()).hexdigest(),
        "control_sha256": hashlib.sha256(a.control.read_bytes()).hexdigest() if a.control else None,
    }, default=str, indent=2) + "\n")
    cpus = {int(x) for x in a.cpus.split(",")}
    assert cpus <= os.sched_getaffinity(0)
    if a.driver_cpu is not None:
        assert a.driver_cpu not in cpus
        os.sched_setaffinity(0, {a.driver_cpu})
    with tempfile.TemporaryDirectory(prefix="slim-data-") as tmp:
        tmp = Path(tmp)
        for i in range(a.rounds):
            seed = [3179,3181,3187][i%3]
            writes, queries = workload(seed, a.queries)
            results = []
            modes = list(a.modes)
            # Six-round Latin ordering balances start position and alternates
            # order within each pair, including duplicate A/A slots.
            if i % 2:
                modes.reverse()
            turn = (i//2) % len(modes)
            modes = modes[turn:] + modes[:turn]
            for j,mode in enumerate(modes):
                binary = a.control if mode in ("base", "repeat") and a.control else a.binary
                out = measure(binary.resolve(), mode, tmp/(f"{i}-{j}"), writes, queries,
                              a.write_only, cpus, a.mapped_proc)
                results.append(out)
            assert len({e["output_sha256"] for e in results}) == 1, "ordered output differs"
            (a.output/f"round-{i+1:02}.json").write_text(json.dumps(dict(seed=seed, runs=results),indent=2)+"\n")
            print(seed, [(r["mode"], round((r["filtered_ns"]+r["unfiltered_ns"])/1e6,2),
                         round(int(r["samples"]["end"]["memory.peak"])/2**20,2),
                         round(r["write_ns"]/1e6,2)) for r in results], flush=True)
if __name__ == "__main__":
    main()

