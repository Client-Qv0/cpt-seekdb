"""Additional development data, not the organizer's Hidden250K dataset."""
import json
from pathlib import Path
import sys
import numpy as np
from benchmark_offline_ddl import digest, vector

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
n, dim, nq, seed = 250000, 256, 4096, 20261031
rng = np.random.default_rng(seed)
centers = rng.standard_normal((128, dim), dtype=np.float32) * 1.5
scales = np.geomspace(0.25, 2.0, dim).astype(np.float32)
base = (centers[rng.integers(128, size=n)] + rng.standard_normal((n, dim), dtype=np.float32)) * scales
queries = (centers[rng.integers(128, size=nq)] + rng.standard_normal((nq, dim), dtype=np.float32)) * scales
np.save(root / 'base.npy', base)
np.save(root / 'queries.npy', queries)
with (root / 'base.tsv').open('w') as out:
    for i, row in enumerate(base):
        out.write(f'{i}\t{vector(row)}\n')
best_d = np.full((nq, 100), np.inf)
best_i = np.full((nq, 100), -1, dtype=np.int64)
q = queries.astype(np.float64)
qnorm = (q * q).sum(axis=1)[:, None]
for start in range(0, n, 16384):
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
manifest = {'config': dict(n=n, dim=dim, nq=nq, seed=seed,
                         distribution='anisotropic_cluster_mixture_f32'),
            'sha256': {name: digest(root / name) for name in
                       ('base.npy', 'queries.npy', 'truth.npy', 'base.tsv')}}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
