# NN-Descent refinement validation, 2026-10-30

Historical report for `8a4a16ec3fa6620aaf5ed4833717305d133a8d65`.
The subsequent organizer result supplied by the participant was **18.666/20**:
build 2.737x, query 1.451x, gates passed. The development ratios below did not
predict full marks on the organizer's data. See the newer worker/wide-search
report for the next revision; do not treat these results as a score guarantee.

This revision reduces NN-Descent iterations from 65 to 12 on top of
`f4d10eee8817fbe60c693c0f75005f330e65875a`. It retains FP32 inputs, the
128-edge graph, intermediate degree 128, and the supplied hipVS CAGRA search.
No query cache or replacement CPU search was added.

The development measurements reach the published aggregate performance targets.
They are **not an official score**: the organizer's Hidden250K and profiler
checks remain untested by the official harness.

## Paired measurements

The reference is V5 commit `634888d9b037153fa143d2c913ba4b25503e1d62`.
Both native variants were built from source using the supplied dependencies and
TRACE=OFF. The reference reused identical unchanged native objects, replacing
the modified adaptor source and bridge with their V5 versions. The candidate
also passed a complete native build linked to its final bridge.

Each input contains 250,000 FP32 vectors and 4,096 held-out queries. Public SIFT
uses the first 250,000 training vectors and first 4,096 test vectors from
`https://ann-benchmarks.com/sift-128-euclidean.hdf5`; its exact Top-100 ground truth
was recomputed over this prefix. The second input is independent normalized
Gaussian data in 256 dimensions, seed 20261030, **not Hidden250K**. Manifests and
completed raw results are in `results/2026-10-30/`.

| Development input | V5 build + first query | Candidate | Build speedup | Query speedup | Recall@10 | Recall@100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Public SIFT prefix, 128D | 47.793 s | 10.809 s | 4.422x | 1.473x | 0.999902 | 0.999963 |
| Independent synthetic, 256D | 52.551 s | 13.444 s | 3.909x | 1.914x | 0.977124 | 0.952375 |

Applying weights 0.4/0.6 gives **4.106x build** and **1.724x query**.
Query speedup within each input is the geometric mean of Top-10 and Top-100 QPS
ratios. The 1.5x full-score query target applies to the aggregate, while the
per-input regression floor is 0.90x. Thus the SIFT ratio alone is not a failure.
Each Top-k result contained k distinct valid IDs. Recall absolute floors and
the maximum 0.005 decrease relative to V5 passed on these development inputs.
Sampled visible-device VRAM ratios were 0.996 and 1.007, below 1.25.

An earlier run of the same 12-iteration bridge measured 3.040x build and 1.900x
query on 256D, and 4.494x/1.481x on SIFT. Timing varies; the latest completed
runs above are preserved without treating these observations as cloud guarantees.

## Verification and limits

- Full seekdb build and hipVS bridge build passed with the fixed dependency set.
- Native persistence write/read cases passed, including invalid-shape rejection.
- GPU-to-host dataset restoration matched the original FP32 values bit for bit.
- SQL VSAG execution, snapshot restart, filtered lazy-host fallback, deletion,
  and insertion of a large primary key passed in the final 256D run.
- Snapshot I/O ASan/UBSan checks and existing dataset preparation unit tests passed.
- External profiling during development observed NN-Descent and CAGRA search
  kernels. Final official GPU-path certification remains organizer-controlled.

The development container had 16 CPU cores by quota and 55 GiB memory, with
ROCm 7.2.4 and a gfx1100 device. VRAM was sampled at 20 Hz only for devices
exposed through `/dev/dri`; sampling cannot prove the exact instantaneous peak.
SQL build timing starts after data import and includes the first legal query.
Top-10/100 each execute 4,096 individual SQL statements with the published
index parameters and ef_search=64. Every run starts a fresh isolated instance.

The candidate source was pinned using a Git archive of the parent commit plus
the bridge change above. Building below a notebook Git checkout affected the
embedded revision metadata; it is not used as source provenance. Final native
artifact hashes are recorded in `binaries.sha256`; binaries are not submitted.

## Reproduction

Use the contest build commands, including `OB_BUILD_CUVS_TRACE=OFF`, and Python
with numpy, PyMySQL, and h5py for the development scripts. Compile the V5 and
candidate binaries separately with their corresponding bridge libraries.

Prepare public SIFT with:

```sh
python prepare_public_sift.py sift-128-euclidean.hdf5 /data/public-sift/data-128
```

Prepare synthetic data by calling `benchmark_offline_ddl.prepare` with
`n=250000, dim=256, nq=4096, seed=20261030`; prepare a 128D sibling for lifecycle
checks as well. This exact FP32 preparation and truth computation are outside
the measured interval.

Run each binary against the same data, with a unique, nonexistent run directory:

```sh
python benchmark_contest_sql.py --binary /build/seekdb --bridge-dir /build \
  --root /runs/unique-candidate --data-root /data/public-sift \
  --label candidate --dims 128 --skip-lifecycle \
  --baseline-result /runs/v5/result.json
```

Use `--label baseline` for V5. For 256D, use its data root and `--dims 256`,
omitting `--skip-lifecycle` to include the additional SQL checks. The optional
build-speedup cutoff is a conservative early stop, not the official aggregate
scoring rule. To reproduce the aggregate from the committed records:

```sh
r=results/2026-10-30
python summarize_contest_pair.py \
  --source-parent-commit f4d10eee8817fbe60c693c0f75005f330e65875a \
  --nn-descent-iterations 12 \
  --sift-baseline "$r/baseline-public-sift.json" \
  --sift-candidate "$r/candidate-public-sift-final.json" \
  --other-baseline "$r/baseline-synthetic-256.json" \
  --other-candidate "$r/candidate-synthetic-256-final.json" \
  --output /tmp/seekdb-development-summary.json
```
