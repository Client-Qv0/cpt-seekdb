"""Prepare an explicit public SIFT prefix, not organizer/hidden evaluation data."""
import hashlib
import json
from pathlib import Path
import sys
import h5py
import numpy as np

source = Path(sys.argv[1])
root = Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=False)
with h5py.File(source, 'r') as data:
    print({key: data[key].shape for key in data}, flush=True)
    base = np.asarray(data['train'][:250000], dtype=np.float32)
    queries = np.asarray(data['test'][:4096], dtype=np.float32)
assert base.shape == (250000, 128) and queries.shape == (4096, 128)
np.save(root / 'base.npy', base)
np.save(root / 'queries.npy', queries)
with (root / 'base.tsv').open('w') as out:
    for i, row in enumerate(base):
        out.write(str(i) + '\t[' + ','.join(format(float(x), '.9g') for x in row) + ']\n')
best_d = np.full((len(queries), 100), np.inf)
best_i = np.full((len(queries), 100), -1, dtype=np.int64)
q = queries.astype(np.float64)
qnorm = (q * q).sum(axis=1)[:, None]
for start in range(0, len(base), 16384):
    block = base[start:start + 16384].astype(np.float64)
    distances = qnorm + (block * block).sum(axis=1)[None, :] - 2 * (q @ block.T)
    indices = np.argpartition(distances, 99, axis=1)[:, :100]
    nearest = np.take_along_axis(distances, indices, axis=1)
    merged_d = np.concatenate((best_d, nearest), axis=1)
    merged_i = np.concatenate((best_i, indices + start), axis=1)
    keep = np.argsort(merged_d, axis=1, kind='stable')[:, :100]
    best_d = np.take_along_axis(merged_d, keep, axis=1)
    best_i = np.take_along_axis(merged_i, keep, axis=1)
np.save(root / 'truth.npy', best_i)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

manifest = {'config': {'n': len(base), 'dim': 128, 'nq': len(queries),
    'distribution': 'public_SIFT_train_prefix_250000_test_prefix_4096_f32_L2'},
    'source': 'https://ann-benchmarks.com/sift-128-euclidean.hdf5',
    'source_sha256': digest(source),
    'sha256': {name: digest(root / name) for name in ('base.npy', 'queries.npy', 'base.tsv', 'truth.npy')}}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2), flush=True)
