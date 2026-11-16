"""Check persisted floating bits and errors with the actual protocol binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

def variants():
    yield from ("-0", "-0.000000", "+0", "+.125", ".0", "1.", "9999999", "-9999999",
                "0.000001", "0.0000001", "-1e-100", "1.4e-45", "1.17549435e-38",
                "3.4028234663852886e38", "1.000000059604644775390625",
                "1.000000059604644775390626", "16777217", "16777219",
                "000000000000000000000001", "+12.345e-3")
    r=random.Random(817)
    for _ in range(3200):
        n=r.randrange(10**7)
        k=r.randrange(7)
        digits=str(n).zfill(k+1)
        number=digits[:-k]+"."+digits[-k:] if k else digits
        yield r.choice(("-","","+"))+number

def run(bin, directory, sqls):
    p=subprocess.Popen([str(bin),"--data-dir",str(directory)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    assert json.loads(p.stdout.readline())=={"type":"ready"}
    log=[]
    try:
        for i,sql in enumerate(sqls+[None]):
            req = {"id":i,"op":"execute","sql":sql} if sql is not None else {"id":i,"op":"shutdown"}
            p.stdin.write(json.dumps(req,separators=(",",":")).encode()+b"\n");p.stdin.flush()
            raw=p.stdout.readline()
            assert raw,(i,sql,p.poll())
            ack=json.loads(raw)
            assert ack["id"]==i,ack
            log.append(raw)
        assert p.wait(timeout=15)==0
        data=(directory/"journal.mvdb").read_bytes()
        return log,data
    finally:
        if p.poll() is None: p.kill();p.wait()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("baseline",type=Path)
    p.add_argument("candidate",type=Path)
    a=p.parse_args()
    rows=list(variants())
    invalid=["[1.0e]","[+]","[1.0.2]","[nan]","[1e99]","[1,2]","[.]"]
    sql=["CREATE TABLE d (id BIGINT PRIMARY KEY,v VECTOR(1));"]
    for j in range(0,len(rows),100):
        sql.append("INSERT INTO d VALUES "+",".join(f"({i},'[{rows[i]}]')"
                   for i in range(j,min(j+100,len(rows))))+";")
    good=len(sql)
    sql.extend(f"INSERT INTO d VALUES ({90000+i},'{v}');" for i,v in enumerate(invalid))
    sql.append("SELECT id,v FROM d ORDER BY id LIMIT 13;")
    with tempfile.TemporaryDirectory() as tmp:
        aout,awal=run(a.baseline,Path(tmp)/"base",sql)
        bout,bwal=run(a.candidate,Path(tmp)/"candidate",sql)
        assert len(aout)==len(bout)
        for i,(line,other) in enumerate(zip(aout,bout)):
            assert line==other,(i,line,other)
            assert json.loads(line)["ok"] == (not good<=i<good+len(invalid)),(i,line)
        assert awal==bwal,"persisted WAL differs"
        print(json.dumps(dict(valid_components=len(rows),invalid_inputs=len(invalid),
          ordered_replies_match=True,wal_byte_identical=True,wal_sha256=hashlib.sha256(awal).hexdigest())))
if __name__=="__main__":
    main()

