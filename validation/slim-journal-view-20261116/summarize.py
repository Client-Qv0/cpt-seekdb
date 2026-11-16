"""Summarize matched runs without assuming platform score units."""
import argparse
import json
import math
from pathlib import Path
import random
import statistics as st

def stats(values):
    rng = random.Random(20261116)
    draws = sorted(st.median(rng.choices(values, k=len(values))) for _ in range(10000))
    return dict(median=st.median(values), iqr=st.quantiles(values, n=4, method="inclusive")[2]
                -st.quantiles(values, n=4, method="inclusive")[0],
                ci95=[draws[250],draws[9749]], wins=sum(v < 0 for v in values))

def metric(r, key):
    if key == "mixed":
        return r["filtered_ns"]+r["unfiltered_ns"]
    return r[key+"_ns"]

def io(r, device):
    data = r["samples"]["end"]["io.stat"]
    line = next((x for x in data.splitlines() if x.split()[0] == device), None)
    if line is None:
        raise ValueError((device,data))
    fields = dict(part.split("=") for part in line.split()[1:])
    return int(fields["rbytes"]),int(fields["wbytes"])

def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--device", required=True)
    a = p.parse_args()
    rounds = [json.loads(f.read_text()) for f in sorted(a.directory.glob("round-*.json"))]
    print("n=",len(rounds))
    for mode in ("row","mapped","repeat"):
        pairs = [(next(r for r in f["runs"] if r["mode"]=="base"),
                  next((r for r in f["runs"] if r["mode"]==mode),None),
                  next((r for r in f["runs"] if r["mode"]=="repeat"),None)) for f in rounds]
        if not all(c is not None for _,c,_ in pairs):
            continue
        for k in ("mixed","filtered","unfiltered","write"):
            for denominator in (("base","both") if mode=="mapped" and pairs[0][2] else ("base",)):
                v = [100*(metric(c,k)/(math.sqrt(metric(b,k)*metric(b2,k)) if denominator=="both"
                                       else metric(b,k))-1) for b,c,b2 in pairs]
                print(mode,k,denominator,stats(v))
        m = [(int(c["samples"]["end"]["memory.peak"])-int(b["samples"]["end"]["memory.peak"]))/2**20 for b,c,_ in pairs]
        print(mode,"memory_delta_MiB",stats(m),"minmax",[min(m),max(m)])
        physical = [(io(b,a.device),io(c,a.device)) for b,c,_ in pairs]
        print(mode,"io_range", [sorted(set(x[i] for x in physical)) for i in (0,1)])
if __name__ == "__main__":
    main()

