# Q7 filtered-code-block experiment

Date: 2026-11-15

## Decision

**Reject the production implementation and keep the negative evidence.**

The posting-aligned int8 code cache was correct and stayed within its memory
gate, but the controlled formal-JSONL benchmark showed no end-to-end gain. The
filtered-query median was `0.9974x` and total-query median was `0.9926x`
(baseline time / candidate time), with candidate wins in only 9 of 20 pairs.
This is below both the `1.10x` filtered and `1.05x` mixed-query retention
targets.

The source and tests were restored to the `9d82b2f` baseline. The tested diff is
preserved in `rejected-filter-code-blocks.patch` for audit and for reuse only if
a later, stronger screening kernel justifies another experiment.

## Starting point

- Git branch: `perf/q7-filter-blocks-li-20261115`
- Starting commit: `9d82b2fe3e105b0a19122e972783da5c344b90f8`
- Performance source corresponds to `5126ac92cc38fdf2f03cd0fb4b5024702286622d`
- Baseline binary:
  `f230d02770de81a2c507fbf6f7d8736fa40776512a0faffbf34eb7cce98d72c8`
- Candidate binary:
  `de56b3342db1425b8b04a4e211bcdd472bbbd90e7948883ae401bad8f455ffed`

The candidate lazily copied every row-major int8 screening code into a
second array ordered exactly like the equality posting. A single equal-value
run then became a contiguous block while postings, float32 refinement, TopK
merge, distance calculation, and primary-key tie-breaking stayed unchanged.
It used a 1.5 MiB hard cap and fell back to the existing row-major code array
when that cap or the broader exact-view budget was exceeded.

## Workload and environment

Every measured database process used the default formal JSONL entry, a fresh
data directory, `CPUQuota=200%`, `MemoryMax=2 GiB`, and swap disabled. Local
runs were also pinned to CPUs 0 and 1 with `taskset` to reduce scheduler drift;
this pinning is a local measurement control and is not an official-scoring
claim.

Workload:

- 10,000 rows
- 128 dimensions
- 100 rows per INSERT
- 1,000 TopK-10 queries
- 500 equality-filtered and 500 unfiltered queries
- three deterministic seeds: 3179, 3181, and 3187
- ten repetitions of the same query set per process to reduce timer noise

The runner is `paired_filter_benchmark.py` in this directory. It records raw
cgroup CPU, memory, swap, memory events, and `io.stat`, and compares the
complete response sequence between variants.

## Results

The baseline/candidate time ratio is reported. A ratio above 1 means the
candidate was faster.

| Data | Total median | Filtered median | Unfiltered median | Total wins |
|---|---:|---:|---:|---:|
| A/A, 20 pairs, same binary | 0.9953x | 0.9860x | 1.0002x | 10/20 |
| A/B, 20 ABBA pairs | 0.9926x | 0.9974x | 0.9934x | 9/20 |

A/A total IQR was `0.0480`; A/B total IQR was `0.0952`. The A/B candidate had
no signal above the same-binary noise floor and was slightly slower at the
median on every reported surface.

Memory and I/O:

- A/A memory-peak delta: median `4,096 B`, maximum `208,896 B`
- A/B memory-peak delta: median `1,257,472 B`, maximum `1,499,136 B`
- Candidate code payload for 10,000 x 128 is `1,280,000 B`
- A/B read-byte delta: `0 B` in every pair
- A/B write-byte delta: `0 B` in every pair

The `1.5 MiB` memory ceiling was respected, but memory without speed is not a
reason to keep the feature.

## Correctness evidence

- Release CTest: `9/9`
- Stress acceptance: `21/21`
- Optimization/large acceptance: `17/17`
- Official public package: `20/20` cases, 95 SQL statements
- Candidate and baseline returned the same complete response sequence in all
  20 A/B pairs
- Independent NumPy oracle: `1000/1000` queries passed
- Filtered oracle recall@10: `1.0`
- Unfiltered oracle recall@10: `1.0`
- Maximum absolute distance error: `7.105427357601002e-15`
- Unit coverage included posting order, missing values, budget fallback,
  repeated allocation reuse, four-row/eight-row integer-kernel bit equality,
  update invalidation, and filtered TopK behavior

## Interpretation

The equality posting already selects the correct roughly 2,000-row candidate
partition, and the general scan visits only 20% of the table for these queries.
The tested coarse-screen kernel was already sequential over the four/eight rows
given to it. Reordering those rows removed scattered code loads, but introduced
an extra 1.25 MiB working set that competes with the existing compact view and
screening codes. The screening stage was therefore not a large enough fraction
of filtered latency to create a measurable end-to-end result.

This is a negative result for **duplicating all codes in posting order**. It
does not rule out a screening method that reduces the number of dimensions or
rows examined.

## Next experiment

Do not merge or submit this implementation. Revert `src/` and `tests/`, then run
the already planned offline quantized-prefix lower-bound probe:

1. Instrument only a diagnostic build.
2. At 16, 32, 64, and 96 dimensions, measure how many candidates can be safely
   rejected after the TopK heap is full.
3. Use a conservative lower bound with quantization and square-root rounding
   error included.
4. Require roughly 70% safe rejection at 64 dimensions before writing a
   production kernel.
5. If that probe fails, stop the coarse-screening branch and move to
   7-bit biased dot products or data-gated exact IVF rather than adding another
   contiguous copy variant.
