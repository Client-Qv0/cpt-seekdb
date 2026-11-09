# Public admission bridge and exact-query experiments

Date: 2026-11-09. Base: 75ecbf3e60a68de7d833aa899bc0fcb4c48df47e. Branch perf/exact-query-li-20261109. All development/execution occurred on SSH server A-li, isolated worktree /opt/minivectordb-v2-query. No official submission.

## Decision

Keep production V2 unchanged. Deliver the public-case local bridge, Dockerfile verification, query decomposition and experimental prototypes with complete positive/negative results. Neither tested production-query prototype met the predeclared 20% median end-to-end improvement target; block checking also regressed in one pair. Their sources and tests are preserved under prototype-*-source, but the default src/ and CMakeLists.txt were restored to the base. This is not a claim that query optimization is complete or that UPDATE latency is fixed.

The full contiguous cache has NOT been integrated into Engine. A standalone layout component validates contiguous vectors plus runtime string-equality postings and budget admission, but does not establish full database performance, cache invalidation correctness or container memory. These integration questions remain future work. This narrower first experiment avoided adding permanent memory or changing transaction/WAL logic while testing the measured execution hotspot.

## P0: official public package and Docker

Official package fixed commit 9f6df2ba5acf871376e22b64a3d0724e4b575044; manifest minivectordb-public-v4. fetch_public.py validates each downloaded Git blob SHA-1. Attribution and source URLs remain in package README and binding.json. This package contains20 cases/95 SQL; its README describes29 formal cases but no complete transport driver. Assertion JSON is not a frozen process-output protocol.

New tests/public_samples.py creates one empty data directory per case, retains it across --restart, checks affected rows/columns/ordered or multiset rows and floating tolerance1e-5, preserves BIGINT precision and duplicate multiplicity, and records every actual response. Four focused bridge tests were first red because the module did not exist, then green. The --mode ann directive is explicitly exact fallback only, not ANN coverage. Until error mapping freezes, public README permits failure plus nonempty error code; semantic mappings are not certified here.

Results:
- Native V2 baseline:20/20 cases,95/95 statements pass.
- Actual production Dockerfile no-cache build: successful. Actual container entrypoint:20/20 cases,95/95 statements pass, network disabled,2CPU/128MiB/no swap for local extra pressure.
- Extracted image executable SHA256 78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c, identical to frozen nativeV2. Exact image metadata, build transcript, runtime packages and executable hash saved. Public Docker result binary hash identifies the wrapper script; image ID plus docker-binary.sha256 separately bind the actual executable.
- Blocked pruning prototype:20/20,95/95 pass. Final defaultV2 public20/95 rechecked.

The production Dockerfile still uses mutable Ubuntu tag/apt package selection; successful reconstruction is not proof of future byte-identical builds. No formal29-case admission, final framing/error readiness or ANN implementation is claimed.

## Query decomposition (separate diagnostic)

query_profile_main.cpp links the frozen V2 library and aggregates clocks only in a diagnostic executable.1000 queries: end-to-end2.468302s; Engine execution2.182182s; result serialization/output/flush0.045953s; first query Engine20.974ms. Thus database execution dominates this observation. The residual includes client/pipe/scheduling; it is not a measured pure scheduling time. Engine time is not further split into parser/filter/distance/heap in this experiment. This single diagnostic does not replace the default-binary paired results and does not prove a continuous cache will improve the full workload.

## Exact pruning prototypes

Both prototypes preserve original FP32 inputs, sequential FP64 accumulation, square root distance and stable PK tie handling. Only the existing exact TopK fast path used the helper. Before dropping a candidate, partial squared distance must exceed the square of nextafter(worst_rounded_distance,+infinity); that widened bound conservatively retains rounded square-root ties. No fast-math, ANN, WAL, transaction, persistence or cache-invalidation changes.

Prototype1 checks after each dimension. Prototype2 checks after each8 dimensions to reduce branch overhead; accumulation order remains unchanged. New exact_distance unit tests (asserts explicitly retained under Release) check8000 random vector pairs across1/3/16/128 dimensions and five thresholds each, including adjacent rounded bounds, plus zero/extreme cases. The red compile failed for the absent helper, then both prototypes passed.

Same-host actual cgroup2CPU/cpuset0,1/128MiB/no swap, independent data directories, three alternating pairs per candidate, frozen original SQL/oracle and default executables. All6 runs per variant completed; every6066 query response per experiment passed the independent FP32/FP64 oracle. No extra build workload ran during the paired measurements.

| Variant | V2 control warm-query seconds, all rounds | Prototype seconds, all rounds | Median paired control/prototype | Paired median time reduction |
|---|---|---|---:|---:|
| Every dimension |2.992642,3.077691,2.883978|2.837912,2.685784,2.774547|1.054522|5.1703%|
| Every8 dimensions |2.931221,3.120890,3.168425|2.986332,2.710428,2.871215|1.103514|9.3804%|

The second prototype's first pair regressed by about1.88%. Only three pairs and partially balanced order: these are limited local observations, not broad speed guarantees. Neither reaches20%; do not cherry-pick the fastest pair. Complete write/startup/prewarm/resource metrics and all negative stages remain in each summary.json. This is not an official performance score: frozen official baseline and calibrated physical I/O are absent.

## Standalone contiguous layout probe

columnar_probe.cpp uses actual runtime dimensions/group strings, contiguous FP32 matrix, IDs and equality postings. It first checks conservative admission before allocating. Original variant-row and columnar paths independently produce and exactly compare ordered TopK results, preserving sequential FP64 arithmetic.

-10k×128,7 groups:100/100 query comparisons pass; estimated matrix/ID/postings capacities5,315,633 bytes, component build5.078ms, row scan246.762ms vs columnar217.044ms over100 queries.
-37×3,11 groups:100/100 comparisons pass.
-1m×4 exceeds component admission estimate and is rejected without allocating the candidate matrix.

These are ONE in-process layout experiment per shape, with row path always measured first and both reference and prototype data held in memory. The capacity estimate excludes allocator/system bookkeeping; it is not cgroup memory. The times include a shared sorting method and are not a balanced benchmark or end-to-end database gains. No extrapolated official score or claim of a production-ready bounded cache.

## Correctness and resource regression of blocked prototype

- Release CTest6/6 (including meaningful exact_distance asserts), blackbox19/19 with stress enabled, extra regression11/11 with large outputs enabled.
- ASan/UBSan CTest6/6; ordinary blackbox18 pass+1 pressure skip; extra8 pass+large-output class skip. No reported sanitizer error. Skipped cases were separately covered by Release/cgroup, not claimed as sanitizer passes.
- Additional held-out seeds9143 and27183:1000/1000 independently checked queries each, filtered/unfiltered Recall1, max distance error7.105427357601002e-15. These runs are correctness only, not timing evidence. Runtime seed overrides are visible in additional_seeds.py and report seed fields; --verify-workload is intentionally not used against the old3179 generator for these new seeds.
- Actual four-case128MiB cgroup resource regression:4/4,zero errors/failures/skips and zero containerOOM. Several peaks reach134217728 bytes; success does not imply headroom. Intentional SIGKILL exit137 is distinct fromOOM. Raw io.stat remains uncalibrated shared-device observation.
- Million-row memory: one independent load+first-scan per version/schema, with actual cgroup limits. Scalar control/prototype anon after load32,546,816/32,550,912 bytes; after scan38,170,624/38,174,720. Vector4 after load33,099,776/33,099,776; after scan39,186,432/39,186,432. No material loss of V2 compact-index benefit in these samples. All batch acknowledgements, two PK probes and expected scan winners checked; not a full million-row oracle or a timing comparison.

WAL/checkpoint production code is unchanged. Existing CTest/storage and blackbox recovery checks ran on the prototype, but this round did not rerun the separate bidirectional compatibility helper,2m capacity ladder or official hidden cases. Old49+320 evidence files and final default13 production files remain unchanged.

## Reproduction and retained artifacts

- Rebuild blocked prototype with cmake -S validation/exact-query-li-20261109/prototype-blocked-source -B build-query -DCMAKE_BUILD_TYPE=Release; then build and CTest. Its full production inputs match candidate-manifest.json. Initial source snapshot matches candidate-initial-manifest.json. Historic run.json paths describe paths at measurement time, before default source restoration.
- run_pair.sh now points to the frozen blocked source snapshot; supply a NEW output name. Existing paired-initial and paired-blocked outputs must not be overwritten.
- Standalone layout: g++ -std=c++17 -O3 -Isrc validation/exact-query-li-20261109/columnar_probe.cpp -o build-profile/columnar-probe.
- Profile links the unchanged V2 library; do not link the prototype library and label it baseline.
- Database directories remain on the server and are ignored by Git; input SQL, output/reference checks, source snapshots, hashes, scripts and logs are preserved.

Automated delegated review did not produce a usable response in this run; no independent code-review approval is claimed. The primary agent manually reviewed assertion semantics, cleanup, pruning/tie bound, source separation and staged scope. Independent numerical oracles are actual executed tests, not a substitute claim of human review.

No formal assessment, ANN, pwritev or forced branch replacement was performed. Remaining optimization work: integrate and validate a single-budget columnar cache with generic fallback and all mutation/transaction invalidation cases, obtain stronger balanced timings, and split the Engine execution subcomponents. The original isolated UPDATE slow case remains unresolved and is not changed by this work package.
