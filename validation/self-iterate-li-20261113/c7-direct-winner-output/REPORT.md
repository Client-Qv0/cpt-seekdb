# C7 direct compact winner projection

## Result

Retain this optimization as successful performance commit 1/5.

The exact Top-K fast path already keeps the full table in an exact `Compact` view. Previously, after selecting winners it issued a separate `Store::get`, decoded every projected value from disk bytes, and recomputed distance. C7 stores each winner's compact row index and projects winners directly from the resident view. Rows outside a complete compact view retain the original store-based fallback.

The final-source six-pair A/B measured a **8.688% median query-time reduction with 6/6 wins**. The write path is unchanged and measured a **0.794% median reduction with 5/6 wins** (no regression); peak process RSS median improved 0.549%. Data file bytes were identical in every pair.

## Semantics

- Ordered distance projections reuse the exact sort distance only when both the vector column and query vector match the `ORDER BY` distance.
- Additional `L2_DISTANCE` expressions are recomputed exactly from the compact vector with their own query.
- BIGINT, VARCHAR, VECTOR, repeated distance projections, multiple distinct distances, K/tie ordering, filters, transaction update invalidation, rollback and restart retain their original semantics.
- Missing or bypassed compact views use the original `Store::get` plus full projection path.
- The cache never publishes a partially filled view; output uses the same compact state that was searched.

The first implementation incorrectly reused the sort distance for every distance projection. `optimization_acceptance.py` exposed `1` versus `sqrt(2)`. A targeted different-distance regression was added, and the corrected implementation passed the full suite.

## Validation

- TDD red: missing compact cell accessors failed compilation.
- TDD red: repeated query with two distinct distance projections returned the sort distance for both.
- Targeted `test_exact_cache`: PASS.
- Targeted `test_engine_extra`: PASS, 33 checks.
- Release CTest: `7/7`.
- Acceptance with stress: `21/21`.
- Optimization and large-output: `16/16`.
- Public bridge: `4/4`.
- Native official public cases: `20/20` cases, 95 SQL.
- Official fixed Docker public cases: `20/20`.
- Docker image binary SHA-256 equals native binary SHA-256:
  `9cccf095a0d8c5f8e98d1538564de1b4b8b51586b404aa073f98cecaef3d407e`.

## Performance method

Every run used a fresh systemd transient cgroup with 2 CPUs (`AllowedCPUs=0-1`), 128 MiB `MemoryMax`, zero swap and a 200% CPU quota. Pairs alternate base-first and candidate-first. The exact base is commit `5f1436e660877559bad07275d92ed8d4357711ee`; the candidate is built from the immediate modified source.

Exploratory evidence consisted of two independent six-pair sets without replacing either set: the aggregate query median was +3.596% with 10/12 wins. The final corrected source was rerun as a new six-pair set shown above. A separate write-only six-pair experiment measured +2.361% with 4/6 wins, resolving the earlier unrelated endpoint noise.

## Artifacts

- `ab-final/`: final-source raw six-pair data and summary.
- `ab-exploratory-combined.json`: two earlier independent sets, retained without replacement.
- `write-only-summary.json`: isolated write-path check.
- `ctest.log`, `acceptance-stress.log`, `optimization-large.log`, `public-bridge.log`.
- `native-public/result.json`, `official-public/result.json`, and corresponding logs.
- `source-binary.sha256`, `image-native-identity.txt`, `image.id`, `docker-build.log`.
- Reproduction scripts and the write-only benchmark.

These are local measurements on a shared host, not an official score. The official generator, physical-I/O accounting and official baseline are unavailable.
