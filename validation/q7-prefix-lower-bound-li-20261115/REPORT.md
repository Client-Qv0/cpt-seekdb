# Quantized-prefix lower-bound probe

Date: 2026-11-15

## Decision

**Stop the prefix lower-bound direction before writing production code.**

Across three deterministic seeds, the conservative query-aware bound rejected
only `0.0028%` of filtered candidates and `0.0338%` of unfiltered candidates at
64 dimensions, versus the required approximately 70%. Even the 96-dimensional
probe reached only about 20.1% filtered and 39.9% unfiltered rejection.

No production source or test was changed.

## Starting point

- Branch: `perf/q7-prefix-lower-bound-li-20261115`
- Parent commit: `71da0ca7731e36ddf27a3efaf79888ad08312119`
- Performance source remains `5126ac92cc38fdf2f03cd0fb4b5024702286622d`
- Output of `git diff -- src tests`: empty
- Seeds: 3179, 3181, 3187
- Rows: 10,000
- Dimensions: 128
- Queries per seed: 1,000, of which 500 are equality-filtered
- TopK: 10

## Bound

The current production disposition chooses one global power-of-two int8 step
from all stored rows. For this workload the probe reproduced:

- `step = 0.015625`
- row code range `[-64, 64]`

Two conservative lower bounds were measured:

1. **Coarse, code-only bound**

   `step^2 * sum(max(abs(row_code-query_code)-1, 0)^2)`

2. **Tighter, query-aware bound**

   `sum(max(abs(step*(row_code-query_code)+query_residual)-step/2, 0)^2)`

The row quantization residual is bounded by `+/- step/2`. The query residual is
known exactly for the active query. The bound is therefore computed only from
the prefix code bytes and query-time data, with no access to the suffix.

Each squared sum is reduced by a conservative `1e-12` factor. Its square root
is moved down one binary64 value, and rejection requires a value strictly above
`nextafter(worst_distance, +infinity)`. This covers quantization and sqrt
rounding in the unsafe direction.

## Scan model

The probe reproduces the current measured scan shape:

- two independent slices when the candidate count is at least 1,024;
- 32-row screening batches;
- each batch uses the heap threshold captured at the batch boundary;
- exact full-vector distances update each slice heap;
- the two slice heaps are merged with distance then primary-key ordering;
- unscreened tails use the same exact distance path.

No prefix was allowed to remove a candidate unless the bound was strictly
above the current worst distance. A candidate at the same distance, even with
an unfavorable primary key, remained in the scan.

## Aggregate results

Rates below are candidate-weighted rejection rates. The three-seed median is
reported outside brackets; the observed seed range is in brackets.

| Surface | Bound | 16-D | 32-D | 64-D | 96-D |
|---|---|---:|---:|---:|---:|
| Filtered | Coarse | 0% | 0% | 0.00219% | 16.55% [16.45%, 16.57%] |
| Filtered | Query-aware | 0% | 0% | **0.00281%** | 20.06% [19.95%, 20.13%] |
| Unfiltered | Coarse | 0% | 0% | 0.02163% | 34.98% [34.80%, 35.35%] |
| Unfiltered | Query-aware | 0% | 0% | **0.03375%** | 39.94% [39.72%, 40.33%] |

The 64-dimensional query-aware result by seed:

| Seed | Filtered | Unfiltered |
|---|---:|---:|
| 3179 | 0.0028125% | 0.03375% |
| 3181 | 0.0039583% | 0.03260% |
| 3187 | 0.0027083% | 0.03847% |

The result is stable across seeds and orders of magnitude below the 70% stop
gate.

## Correctness checks of the probe

- Conservative squared bounds never exceeded the true squared distance in
  randomized tests.
- The query-aware bound was never weaker than the code-only bound.
- The scalar comparison test preserved the required one-ULP margin.
- A zero-rejection simulation returned the exact TopK; this test initially
  failed because of a double-negation bug in heap merging and was fixed under a
  red-green cycle.
- Every one of the 16 combinations of surface, bound, and prefix had
  `topk_mismatches = 0` across all three seeds.
- Query mean sign counts were balanced: 505/495, 465/535, and 522/478.

## Why 96 dimensions is also insufficient

At 96 dimensions, the best rate is about 40% for unfiltered queries. If a
survivor still needs only the remaining 32 dimensions, the expected prefix work
is approximately:

`96 + (1 - 0.40) * 32 = 115.2 bytes` per row, versus 128 bytes for the current
full code scan. That leaves an ideal code-load reduction near 10%, before
branching and query-residual arithmetic, and it requires nine tenths of each
row to be loaded first. This is not a credible path to a 5% end-to-end gain.

## Next direction

Do not implement a production prefix kernel. The next low-cost experiment should
be the 7-bit biased-dot-product screening microbenchmark, because it attacks
the arithmetic of each candidate without adding a second code working set.

For IVF or radius pruning, require an explicit clustered-data gate and an exact
fallback for uniform data. The official 10k workload has no demonstrated
cluster boundary, so IVF should remain a separate branch until a probe shows
enough skipped buckets and zero exact-result changes.

Any later screening geometry that selects a non-prefix dimension subset must be
tested offline first; the contiguous 64-dimension prefix is conclusively too
weak on this workload.
