# Persistent query worker and wider CAGRA search

This revision starts from `8a4a16ec3fa6620aaf5ed4833717305d133a8d65`.
The participant's organizer result for that parent was 18.666/20, with build
2.737x, query 1.451x, and gates passed. Earlier development results were more
optimistic and must not be interpreted as a guarantee on Hidden250K.

## Changes

- Reuse one lazily created 32 MiB-stack pthread for synchronous single-query
  GPU jobs. Previously every SQL query created and joined a new pthread,
  repeatedly initializing runtime thread-local state. The existing registry
  mutex still protects each index and serializes this path. Each job finishes
  before returning; the worker retains no queries, results, or index graphs.
- Use NN-Descent degree/intermediate-degree 64 and 6 iterations, paired with
  the fixed hipVS CAGRA AUTO search, `itopk_size >= 4096`, and width 16. Wider
  GPU search offsets the smaller graph; both quality and SQL performance were
  measured. All input vectors and exposed semantics remain FP32 L2.
- No evaluation-stage switch, input-dependent shortcut, cross-run index cache,
  replacement search implementation, or change to the fixed SQL parameters.
  CPU VSAG, snapshot reload, and filtered/update fallback behavior remain.

## Same-machine comparison with the submitted parent

Each input has 250,000 vectors and 4,096 held-out queries, tested separately at
Top-10 and Top-100 using individual SQL statements. Construction includes DDL
and the first legal query, including lazy worker initialization. Every SQL run
uses a new server/runtime directory, imports its data, and builds a new index.

| Development input | Parent build + first query | New build + first query | Build ratio | Query ratio |
| --- | ---: | ---: | ---: | ---: |
| Public SIFT prefix, 128D | 10.489 s | 7.544 s | 1.390x | 4.984x |
| Independent unit-normal, 256D | 11.891 s | 8.629 s | 1.378x | 4.360x |

These are direct development comparisons against the already submitted code,
not projections of a new official score. Both exceed the extra development
cutoffs of 1.30x build and 1.20x query relative to that parent.

## Frozen V5 comparison and repetition

V5 is `634888d9b037153fa143d2c913ba4b25503e1d62`. Its binary uses V5 adaptor
and bridge sources with identical unchanged native objects. Both variants were
built from source with the supplied dependency set and TRACE=OFF. The candidate
adaptor and new header hashes match the tested binary's compilation inputs;
rebuilding the final bridge source produced a byte-identical library to the
tested experiment. Artifact and source hashes are recorded with the results.

The first synthetic candidate precedes its V5 reference; SIFT uses V5 followed
by the repeated candidate. Candidates were measured twice, with fresh indexes
and runtimes each time. Both runs are retained, including the slower results.

| Input | V5 build | New run 1 | New run 2 | Run 2 build ratio | Run 2 query ratio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public SIFT | 44.960 s | 7.544 s | 6.865 s | 6.550x | 7.472x |
| Unit-normal 256D | 50.884 s | 8.629 s | 8.837 s | 5.758x | 7.457x |

Using the published 0.4/0.6 geometric weights, run 1 gives **5.922x build /
7.382x query**, and run 2 gives **6.063x build / 7.463x query**. Each input's
query ratio is the geometric mean of its Top-10 and Top-100 QPS ratios.
The second input is synthetic development data, **not Hidden250K**.

| Input, run 2 | Recall@10 | Recall@100 | Sampled VRAM / V5 |
| --- | ---: | ---: | ---: |
| Public SIFT | 0.999976 | 0.999968 | 0.907 |
| Unit-normal 256D | 0.997339 | 0.991545 | 0.921 |

Both runs passed absolute recall floors, the maximum 0.005 relative decrease,
exactly k distinct valid IDs, and the sampled VRAM limits. Independent
anisotropic clustered 256D data (250,000 rows, 4,096 queries, seed 20261031)
was additionally checked through the native bridge: recall was 0.999976/1.0,
versus 1.0/1.0 for the parent. That screening is a quality check, not SQL timing.

## Regression evidence

- Full native builds of V5, the parent, and the persistent-worker candidate
  completed. Final bridge rebuilt successfully with the repository build script.
- ASan/UBSan worker test passed: null jobs, 32 MiB stack, thread reuse, recovery
  after a throwing job, and 800 synchronous jobs from 8 concurrent callers.
- SQL `lib=vsag` creation/search, GPU snapshot query after restart, filtering,
  deletion, and insertion of a large primary key passed in `sql-final256.json`.
- Native persistence write/read passed all eight combinations of nq=1/3 and
  Top-10/200, including distinct IDs and exact self-neighbors. Wrong snapshot
  shapes were rejected as expected.
- A separate rocprofv3 run of that native regression observed NN-Descent
  `local_join_kernel` and CAGRA `multi_cta_search::search_kernel`. Profiling was
  excluded from SQL timings. This is development evidence, not the organizer's
  GPU-path certification.
- Final source diff passes whitespace checks. The code remains a descendant
  of the frozen V5 commit and adds no network-fetched native dependencies.

Discarded screening variants and their raw outcomes are retained. In
particular, eight NN-Descent iterations with the original search budget reduced
Top-100 recall by more than 0.005 and were rejected. The accepted configuration
uses the wider search and passed the independent quality checks above.

## Reproduction

Build V5 and the candidate separately with the contest commands documented in
the parent README. Use `benchmark_contest_sql.py` with the respective native
binary and bridge directory. Example from this validation directory:

```sh
python benchmark_contest_sql.py \
  --binary /candidate/seekdb --bridge-dir /candidate/bridge \
  --root /runs/new-candidate --data-root /data/synthetic \
  --label candidate --dims 256 --baseline-result /runs/v5/result.json
```

Prepare SIFT with `prepare_public_sift.py` as in the previous report. Generate
unit-normal data with `benchmark_offline_ddl.prepare(..., 250000, 256, 4096,
20261030)` and a 128D sibling for lifecycle tests. The additional distribution
uses `python prepare_clustered.py /data/clustered/data-256`; its manifest
checksums reproduce the recorded clustered input. Native screening uses:

```sh
python benchmark_bridge_quality.py --bridge /candidate/libseekdb_cuvs_bridge.so \
  --data /data/clustered/data-256 --output /runs/clustered-quality.json
g++ -std=c++17 -g -O1 -pthread -fsanitize=address,undefined \
  ../../../tools/hipvs_bridge/test_search_worker.cpp -o /tmp/test_search_worker
/tmp/test_search_worker
```

Reproduce the aggregate from the committed results:

```sh
r=results/2026-10-30-round2
python summarize_contest_pair.py \
  --source-parent-commit 8a4a16ec3fa6620aaf5ed4833717305d133a8d65 \
  --nn-descent-iterations 6 \
  --sift-baseline "$r/sql-v5-sift.json" \
  --sift-candidate "$r/sql-final-sift-repeat.json" \
  --other-baseline "$r/sql-v5-256.json" \
  --other-candidate "$r/sql-final256-repeat.json" \
  --output /tmp/worker-wide-summary.json
```

## Limits

Development used gfx1100, ROCm 7.2.4, a 16-core CPU quota and 55 GiB host-memory
quota. The official workload uses different CPU/resource limits and includes
unavailable hidden data. Host scheduling, clocks, graph randomness, and input
distribution can change the ratios. VRAM sampling at 20 Hz is not a proof of
the instantaneous allocation peak. Lifecycle restart reports process memory
for the restarted process; non-restart runs preserve their own VmHWM values.

The source archive was built below the notebook checkout, so its embedded
revision string reflects that checkout rather than the submitted revision.
Source/archive provenance and SHA-256 artifacts, not that string, identify the
tested build. Only source and evidence are submitted, never prebuilt binaries.
No official assessment was submitted by the assistant. **Full marks remain
unconfirmed until the organizer evaluates this exact commit.**
