# Seven-bit biased-dot screening experiment

Date: 2026-11-15

## Decision

**Reject the end-to-end candidate and move on to data-gated exact IVF.**

The AVX2 kernel passed its microbenchmark gate and produced every quantized
integer distance exactly. The end-to-end result was real but too small:

- total query median: `1.0371x`
- filtered query median: `1.0158x`
- unfiltered query median: `1.0556x`
- candidate wins: 16/20 pairs

The `1.05x` mixed-query gate was not met. Source and tests were restored after
saving the complete patch in `rejected-7bit-dot.patch`.

## Starting point

- Branch: `perf/q7-7bit-dot-li-20261115`
- Parent commit: `5e02c4208d68b418fe824191168624dbeb717f7d`
- Baseline binary:
  `f230d02770de81a2c507fbf6f7d8736fa40776512a0faffbf34eb7cce98d72c8`
- Candidate binary:
  `fedc49af409951c182d17078d8358ca3f5a8153264e809888c3c5f69f48479aa`

## Candidate

The official workload quantizes to `step=0.015625`, with row and query codes in
`[-64,64]`. For that range the candidate stores each row byte as:

`unsigned = signed_code + 64`

It precomputes each row's signed-code squared norm. A warmed query stores the
signed query codes, their sum, and their squared norm.

The AVX2 kernel computes eight row dot products together:

- `vpmaddubsw(unsigned_row, signed_query)`
- adjacent-pair widening and accumulation
- `distance² = row_norm + query_norm - 2*(biased_dot - 64*query_sum)`

One query load feeds eight independent row accumulators. The result is the same
integer squared-distance value used by the existing quantized threshold.

If any row or query code falls outside `[-64,64]`, the candidate keeps the
existing signed int8/int16 screen. This preserves correctness on datasets that
do not satisfy the seven-bit precondition.

The production layout adds one `uint32_t` row norm per cached row. For 10,000
rows this is about 40 KiB; row code payload does not grow.

## Gate 1: kernel microbenchmark

The comparison uses a palindrome A-A'-B-A'-A sequence, 8,192 hot rows,
128 dimensions, 32-row batches, and 100,000 timed batches per call.

| Metric | Result |
|---|---:|
| Current kernel median | 0.0394017 s |
| Biased-dot kernel median | 0.0286580 s |
| Median speedup | **1.37489x** |
| Rounds above 1.25x | **7/7** |
| Exact batches cross-checked | 256 |

All 32 outputs from every timed batch are consumed, preventing dead-code
elimination. Every checked batch is bit-identical to the current kernel.

## Gate 2: survivor equality

The full official-shaped workload was checked across seeds 3179, 3181, and
3187:

- compared query-candidate pairs: **18,000,000**
- integer distance mismatches: **0**
- maximum absolute integer difference: **0**
- survivor-rate increase: **0.0 percentage points**
- TopK mismatches: **0**

Observed current/candidate survivor rates after the heap filled:

| Seed | Filtered | Unfiltered |
|---|---:|---:|
| 3179 | 7.8923% | 2.4231% |
| 3181 | 7.7914% | 2.4733% |
| 3187 | 7.9034% | 2.4659% |

The candidate does not enlarge the survivor set; it accelerates computation of
the same exact integer screen.

## Gate 3: formal JSONL end to end

Workload:

- 10,000 rows
- 128 dimensions
- 100 rows per INSERT
- 1,000 TopK-10 requests
- 50% equality-filtered
- three seeds
- ten repetitions of the query set per process

Each process used the default formal JSONL entry, `CPUQuota=200%`,
`MemoryMax=2 GiB`, no swap, and local CPU pinning to CPUs 0 and 1.

Ratios are baseline time divided by candidate time.

| 20 ABBA pairs | Total | Filtered | Unfiltered |
|---|---:|---:|---:|
| A/A same binary median | 1.0175x | 1.0232x | 1.0167x |
| A/B candidate median | **1.0371x** | **1.0158x** | **1.0556x** |
| A/B wins | 16/20 | 15/20 | 16/20 |
| A/B IQR | 0.0489 | 0.0428 | 0.0678 |

The unfiltered surface exceeds 5%, but the mixed query workload does not. The
filtered surface improves much less, consistent with pointer-gathered candidate
rows and the surrounding TopK/refinement work limiting the kernel benefit.

Resources:

- maximum candidate memory-peak delta: `184,320 B`
- read-byte delta: `0 B` in every pair
- write-byte delta: `0 B` in every pair
- complete candidate/baseline response sequences equal: 20/20

## Correctness

- Release CTest: 9/9
- Stress acceptance: 21/21
- Optimization/large acceptance: 17/17
- Official public package: 20/20 cases, 95 SQL statements
- Independent NumPy oracle: 1000/1000
- Filtered and unfiltered Recall@10: 1.0
- Maximum absolute distance error: `7.105427357601002e-15`
- Fallback coverage includes codes outside `[-64,64]`
- UPDATE invalidation and biased-layout dispatch covered by engine tests

## Interpretation

The arithmetic microbenchmark is strong and the conversion is exact. The
end-to-end benefit is smaller because the current scan performs this screen
once per candidate batch, and the exact refinement, request handling,
parallel-slice overhead, and filtered candidate traversal remain unchanged.

Combining this kernel with the previously rejected contiguous code copy would
add another 1.25 MiB working set without evidence that the copy is the limiting
factor. That combination should not be pursued without a new profile showing
that filtered code-row locality dominates the remaining latency.

## Next direction

Move to **data-gated exact IVF with radius ordering**. Requirements:

1. sample the table and enable IVF only for clearly clustered data;
2. use a conservative triangle-inequality lower bound;
3. keep float64 exact refinement for every surviving candidate;
4. fall back to the current exact scan for uniform data, sparse filters,
   insufficient bucket savings, memory pressure, and any code-range mismatch;
5. require Recall@10 `1.0`, zero ordered-result changes, and at least a 5%
   mixed-query gain before production consideration.

The official 10k data is uniforms by seed, so IVF is expected to remain a
separate branch unless an additional clustered workload proves the gate.
