"""Exact scalar check of the experimental mapped route, plus invalidation cases."""
import argparse
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import tempfile

def fp32(v):
    return struct.unpack("<f",struct.pack("<f",v))[0]

def distance(row, query):
    acc = 0.0
    for a,b in zip(row,query):
        d = a-b
        acc += d*d
    return math.sqrt(acc)

def cell(vector):
    return "'" + json.dumps(vector, separators=(",",":")) + "'"

def check(binary):
    rng = random.Random(3187)
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.Popen([str(binary),"--data-dir",tmp],stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                             env={"MVDB_SLIM_PROBE":"mapped","LC_ALL":"C"})
        seq = 0
        assert json.loads(p.stdout.readline()) == {"type":"ready"}
        def request(sql=None):
            nonlocal seq
            seq += 1
            request = {"id":seq,"op":"shutdown"} if sql is None else {
                "id":seq,"op":"execute","sql":sql,"search_mode":"exact"}
            p.stdin.write(json.dumps(request)+"\n")
            p.stdin.flush()
            r=json.loads(p.stdout.readline())
            assert r["id"]==seq and r["ok"],r
            return r
        def gen():
            return [round(rng.uniform(-1,1),6) for _ in range(128)]
        def rounded(v):
            return tuple(map(fp32,v))
        fixed=[-0.25]*128
        rows={k:fixed if k in range(30) else gen() for k in range(2053)}
        physical=list(rows)
        rng.shuffle(physical)
        request("CREATE TABLE t (id BIGINT PRIMARY KEY, v VECTOR(128), grp VARCHAR(8));")
        for b in range(0,len(physical),100):
            request("INSERT INTO t VALUES "+",".join(f"({k},{cell(rows[k])},'g{k%2}')" for k in physical[b:b+100])+";")
        truth={i:rounded(v) for i,v in rows.items()}
        tested=0
        def verify(v,filtered=False,desc=False,project=False):
            nonlocal tested
            q=rounded(v)
            where=" WHERE grp='g1'" if filtered else ""
            order=" DESC" if desc else ""
            cols=",v" if project else ""
            actual=request(f"SELECT id,L2_DISTANCE(v,{cell(v)}) AS d{cols} FROM t{where} ORDER BY d{order} LIMIT 10;")["rows"]
            ref=sorted(((distance(row,q),key) for key,row in truth.items() if not filtered or key%2==1),
                       key=lambda x:(-x[0] if desc else x[0],x[1]))[:10]
            assert len(actual)==len(ref)
            for row,(d,key) in zip(actual,ref):
                assert row[0]==key and struct.pack("<d", row[1])==struct.pack("<d", d), (row, d,key)
                if project:
                    assert rounded(row[2])==truth[key]
            tested += 1
        verify(fixed)
        verify(fixed,True,project=True)
        for i in range(24):
            verify(gen(), i%2==0,desc=i%7==0)
        verify([3.0]*128)  # quantized query code range fallback
        old=truth[150]
        request("BEGIN;")
        request(f"UPDATE t SET v={cell(fixed)} WHERE id=150;")
        truth[150]=rounded(fixed)
        verify(fixed)
        request("ROLLBACK;")
        truth[150]=old
        verify(fixed)
        request("DELETE FROM t WHERE id=0;")
        del truth[0]
        verify(fixed,project=True)
        request()
        assert p.wait(timeout=15)==0
        log=p.stderr.read()
        assert log.splitlines().count("SLIM_PROBE mapped")==3,log
        print(json.dumps({"ordered_bitwise_scalar_queries":tested,"mapped_builds":3,
                          "tested":["ties", "shuffle", "projection", "descending",
                                    "query code fallback", "rollback","delete"]}))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("binary",type=Path)
    check(p.parse_args().binary.resolve())

