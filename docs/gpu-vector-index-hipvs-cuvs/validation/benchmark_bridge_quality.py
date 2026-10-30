"""GPU bridge quality screening; not SQL performance or an official score."""
import argparse
import ctypes as c
import json
from pathlib import Path
import time
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('--bridge', required=True)
p.add_argument('--data', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
lib = c.CDLL(a.bridge)
fp = c.POINTER(c.c_float)
up = c.POINTER(c.c_uint)
lib.seekdb_cuvs_build.argtypes = [fp, c.c_long, c.c_long]
lib.seekdb_cuvs_build.restype = c.c_void_p
lib.seekdb_cuvs_search.argtypes = [c.c_void_p, fp, c.c_long, c.c_long, up, fp]
lib.seekdb_cuvs_free.argtypes = [c.c_void_p]
base = np.load(a.data / 'base.npy')
queries = np.load(a.data / 'queries.npy')
truth = np.load(a.data / 'truth.npy')
start = time.perf_counter()
h = lib.seekdb_cuvs_build(base.ctypes.data_as(fp), *base.shape)
assert h
report = {'bridge': a.bridge, 'data': str(a.data), 'build_s': time.perf_counter() - start, 'queries': {}}
try:
    for k in (10, 100):
        ids = np.empty((len(queries), k), dtype=np.uint32)
        distances = np.empty(k, dtype=np.float32)
        start = time.perf_counter()
        for q in range(len(queries)):
            rc = lib.seekdb_cuvs_search(h, queries[q].ctypes.data_as(fp), 1, k,
                                        ids[q].ctypes.data_as(up), distances.ctypes.data_as(fp))
            assert rc == 0 and np.isfinite(distances).all()
        seconds = time.perf_counter() - start
        assert (ids < len(base)).all()
        assert all(len(set(row)) == k for row in ids)
        recall = sum(len(set(row) & set(gt[:k])) for row, gt in zip(ids, truth)) / (len(queries) * k)
        report['queries'][str(k)] = {'qps': len(queries) / seconds, 'recall': recall}
        print(json.dumps(report), flush=True)
finally:
    lib.seekdb_cuvs_free(h)
a.output.write_text(json.dumps(report, indent=2) + '\n')
