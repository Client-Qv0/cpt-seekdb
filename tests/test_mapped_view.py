#!/usr/bin/env python3
"""Exercise the default mapped exact path, including WAL replacement and restart."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import select
import struct
import subprocess
import tempfile


def vec(x):
    return "'[" + ",".join([str(x)]*128) + "]'"


S = lambda needle, where="", order="", extra="": (
    f"SELECT id,L2_DISTANCE(v,{vec(needle)}) AS d{extra} FROM t{where} ORDER BY d{order} LIMIT 10;")


def check(binary, directory, cgroup):
    journal = directory/"journal.mvdb"
    count = 4097
    k = count-1
    file = None
    p = None

    def start():
        nonlocal p,file
        file = tempfile.TemporaryFile()
        def enter():
            if cgroup:
                (cgroup/"cgroup.procs").write_text(str(os.getpid()))
        p = subprocess.Popen([binary,"--data-dir",str(directory)],stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=file,preexec_fn=enter)
        assert json.loads(receive()) == {"type":"ready"}

    def receive():
        assert select.select([p.stdout],[],[],30)[0], "response timeout"
        raw = p.stdout.readline()
        if not raw:
            file.seek(0)
            raise AssertionError(file.read())
        return raw

    def req(sql=None):
        m = {"id":7,"op":"execute","sql":sql} if sql else {"id":7,"op":"shutdown"}
        p.stdin.write(json.dumps(m).encode()+b"\n")
        p.stdin.flush()
        r=json.loads(receive())
        assert r["id"]==7 and r["ok"], r
        return r

    def mapped(enabled):
        assert (str(journal) in Path(f"/proc/{p.pid}/maps").read_text()) == enabled, (
            "expected map" if enabled else "expected no map")

    def verify(sql, ids, distances, projected=None):
        rows=req(sql)["rows"]
        assert [r[0] for r in rows]==ids, rows
        assert [struct.pack("<d",r[1]) for r in rows]==[struct.pack("<d",x) for x in distances], rows
        if projected is not None:
            assert rows[0][2]==[projected]*128, rows[0]

    def kill():
        p.kill()
        assert p.wait(timeout=30)==-9
        file.close()

    try:
        start()
        req("CREATE TABLE t (grp VARCHAR(16), id BIGINT PRIMARY KEY, v VECTOR(128));")
        physical=list(range(count))
        random.Random(3187).shuffle(physical)
        for b in range(0,count,100):
            req("INSERT INTO t VALUES "+",".join(
                f"('g{i%2}',{i},{vec(1 if i==k else 0)})" for i in physical[b:b+100])+";")
        z=math.sqrt(128.0)
        expected=[k]+list(range(9))
        # An unsupported query may be the very first query that builds a view.
        # Rejecting its code must not reject an otherwise valid mapped cache.
        verify(S(1024),expected,[math.sqrt(128*1023**2)]+[math.sqrt(128*1024**2)]*9)
        mapped(True)
        verify(S(1),expected,[0.0]+[z]*9)
        mapped(True)
        verify(S(1," WHERE grp='g0'",extra=",v"),[k]+list(range(0,18,2)),[0.0]+[z]*9,1)
        mapped(True)
        # Code 65 exercises the integer fallback without discarding the map.
        wide = 65.0/64.0
        verify(S(wide),expected,[z/64.0]+[math.sqrt(128*wide**2)]*9)
        mapped(True)
        verify(S(1024),expected,[math.sqrt(128*1023**2)]+[math.sqrt(128*1024**2)]*9)
        mapped(True)
        verify(S(1),expected,[0.0]+[z]*9)
        mapped(True)
        # Repeated unsupported queries must remain exact and keep the mapping.
        for needle in (4, 1024, -1024):
            winners = expected if needle > 0 else list(range(10))
            distances = ([math.sqrt(128*(needle-1)**2)] +
                         [math.sqrt(128*needle**2)]*9 if needle > 0 else
                         [math.sqrt(128*needle**2)]*10)
            verify(S(needle),winners,distances)
            mapped(True)
        req("BEGIN;")
        req(f"UPDATE t SET v={vec(1)} WHERE id=2;")
        verify(S(1),[2,k,0,1,3,4,5,6,7,8],[0.0,0.0]+[z]*8)
        mapped(False)
        req("ROLLBACK;")
        verify(S(1),expected,[0.0]+[z]*9)
        mapped(True)
        verify(S(1,order=" DESC"),list(range(10)),[z]*10)
        mapped(True)
        verify(S(1),expected,[0.0]+[z]*9)
        mapped(True)

        # Grow an obsolete payload beyond the automatic checkpoint threshold.
        # The next BEGIN invokes compaction; inode change proves actual replacement.
        req("CREATE TABLE junk (id BIGINT PRIMARY KEY,s VARCHAR(524288));")
        payload="Q"*(512*1024)
        req(f"INSERT INTO junk VALUES(1,'{payload}');")
        for i in range(40):
            if journal.stat().st_size >= 16*2**20:
                break
            req(f"UPDATE junk SET s='{payload[:-1]}{i%10}' WHERE id=1;")
        before=journal.stat()
        assert before.st_size>=16*2**20
        req("BEGIN;")
        after=journal.stat()
        assert before.st_ino!=after.st_ino and after.st_size<before.st_size
        req("COMMIT;")
        verify(S(1),expected,[0.0]+[z]*9)
        mapped(True)

        req(f"UPDATE t SET v={vec(1)} WHERE id=4;")
        verify(S(1),[4,k,0,1,2,3,5,6,7,8],[0.0,0.0]+[z]*8)
        mapped(True)
        req("BEGIN;")
        req(f"UPDATE t SET v={vec(1)} WHERE id=6;")
        kill()
        start()
        verify(S(1),[4,k,0,1,2,3,5,6,7,8],[0.0,0.0]+[z]*8)
        mapped(True)

        # Vary individual components as well as whole-vector values, and use
        # ordered FP64 accumulation over independently rounded FP32 inputs.
        rng = random.Random(3179)
        def samples():
            return [round(rng.uniform(-1,1),6) for _ in range(128)]
        def fp32(values):
            return struct.unpack("<128f", struct.pack("<128f", *values))
        vectors = {i:(float(i in (4,k)),)*128 for i in range(count)}
        req("BEGIN;")
        for i in range(100,140):
            values = samples()
            req(f"UPDATE t SET v='{json.dumps(values)}' WHERE id={i};")
            vectors[i] = fp32(values)
        req("COMMIT;")
        # Include out-of-code queries and FP32 overflow with finite FP64 sums.
        scales = [1.0] * 8 + [3.0, -3.0] * 2 + [1e20, -1e20] * 2
        for i, scale in enumerate(scales):
            values = [value * scale for value in samples()]
            query = fp32(values)
            reference = []
            for key,row in vectors.items():
                if i%2 and key%2:
                    continue
                total = 0.0
                for a,b in zip(row,query):
                    delta = a-b
                    total += delta*delta
                reference.append((math.sqrt(total),key))
            winners = sorted(reference)[:10]
            where = " WHERE grp='g0'" if i%2 else ""
            verify(f"SELECT id,L2_DISTANCE(v,'{json.dumps(values)}') AS d "
                   f"FROM t{where} ORDER BY d LIMIT 10;",
                   [key for _,key in winners],[distance for distance,_ in winners])
            mapped(True)
        req()
        assert p.wait(timeout=30)==0
        print(json.dumps({"passed":True,"checkpoint_bytes":[before.st_size,after.st_size],
                          "wal_replaced":True,"sigkill_rollback":True,"scalar_queries":len(scales)}))
    finally:
        if p and p.poll() is None:
            p.kill()
            p.wait()
        if file:
            file.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--cgroup",type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mvdb-mapped-view-") as tmp:
        check(str(args.binary.resolve()),Path(tmp),args.cgroup)
