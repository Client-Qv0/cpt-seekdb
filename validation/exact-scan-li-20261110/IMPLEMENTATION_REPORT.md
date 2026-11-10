# Structural EXACT scan — measurement gates completed (2026-11-11)

Current server A-li only; branch perf/exact-scan-li-20261110; initial ef2cece289850201576c6dc7da1db58ef5a99bad; production baseline 9cea05e182875ae16f3f3c9c8e9cc688a65d653c. C1 07b3a75ec2b0434105ccfa51a03a90d07c077ee3 and C2 3490b490cfeb2b0ece00bb637f231e1b2f05ca80 each independently passed scoped spec and quality review. All approved measurement and resource gates and the final independent spec/quality audit passed; C1+C2 combination is retained.

AA_GATE_1.json: six A/A pairs, median absolute change 1.78641%, maximum 4.83542%, PASS; no retry. Baseline native diagnostic first query 20.951ms; CPU samples projection 69.44%, scalar comparison 7.87%, TopK visitor 3.25% (mixed/inlined), zero lost samples. Initial diagnostic wrong CLI preserved; retry passed.

The frozen portable harness uses independent FP32 oracle, full responses and output consumption, 2 CPU pinned 0,1, 128MiB, zero swap, separate data directories, alternating ordering and no concurrent performance jobs. COMPARISONS.json validates all paired results, same workload hashes, recall/order/filters, real cgroups, exits and zero OOM. Numbers are medians of per-pair 100*(1-candidate/base), not a ratio of medians. All rounds and events remain in the named directories.

| Direct comparison | Main query reduction / wins | Overflow query reduction | Overflow write reduction | Overflow restart reduction |
| --- | ---: | ---: | ---: | ---: |
| C1 / baseline | 5.879%, 5/6 | 0.592% | 2.887% | 9.836% |
| C2 / C1 | 34.791%, 6/6 | -0.097% | -0.824% | -0.670% |
| C2 / baseline | 38.413%, 6/6 | -1.935% | -0.675% | -6.028% |

Negative reductions are regressions. C1 alone misses the 15% main gate. C2/baseline main filtered and unfiltered reductions were 27.464% and 45.653%; writes regressed 3.882% and restart-ready improved 3.312%. Overflow stayed within query/write 5% and restart 10% limits. Holdout seeds 65003,65011,65027: 40.643% median query reduction, 3/3 wins. Main, holdout and resource gates passed; final independent spec/quality review also passed (FINAL_REVIEW.md).

Cache construction is a real cost: C2/baseline first query slowed in all six pairs, paired median 54.732% regression, baseline 22.675–32.605ms, C2 36.189–47.033ms. The first query includes sizing and filling; OS page cache was not globally cleared. No separate first-query gate was approved. Raw io.stat is kept as sampled; page-cache attribution and asynchronous writeback prevent treating it as complete physical I/O. Restart time includes Docker startup and recovery. Peaks and memory.events (including max/pressure when present) are separate from OOM; do not interpret a max event as an OOM.

Same-environment rebuilt 7637 direct three main pairs: query median 36.82% faster, write 34.33% faster, restart-ready 23.29% slower, first query 65.93% slower. This is distinct from approved 9cea gate; no official score prediction. Historical 2277.870638 belongs only to 7637.

C2 correctness: native Release CTest 7/7, acceptance 21/21 stress and optimization 15/15 large; 858 SQL whole-response baseline and independent FP32 oracle cases, 8 native stdio boundary cases. ASan/UBSan CTest 7/7; sanitizer acceptance 20 pass/1 skip and optimization 12 executed pass plus explicit skipped class; see sanitizer logs. SIMD bitwise tests and disassembly show separate multiply/add, no FMA. Non-AVX2 hardware was not physically tested. Unchanged official f4d4e266 public driver 20/20 passed. Actual default Docker 128MiB SIGKILL recovery passed 100 acknowledged batches, 10,000 rows, 1,280,000 FP32 components and rollback of pending changes.

Source hashes: C2 native/docker binary b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67; C2 image sha256:f8ccc8d89f578f5e4905827a08690161a942d041ceea06d05044528c98495bf7; baseline image sha256:14957ef07f665050d3b6bfebf180c4822acea378d5e038e41ad8d9562417407a; C1 image sha256:66e8270735ed4aeaba372ad1c2474608bf8791b90e74119a91edd1b4e080961b. Frozen benchmark 2bf78d1307197b23f08e02f842594e0d8c271b706cd9ac8c303673db0b5bf5ed; adapter 957be1db1ba19565aa5e37935f7394b17a65948706f9fdbe6b1320395837ee81.

Million-row probes completed, all phases passed, zero OOM kills. Scalar sampled anon maxima baseline/C2=40,132,608/40,128,512 B, kernel peaks=96,739,328/96,735,232 B. VECTOR(4)+BIGINT eligible TopK sampled anon=41,291,776/40,566,784 B, kernel peaks=114,642,944/113,995,776 B. Both satisfy the <=5% anon growth gate. Each schema/version has one independent case, not a repeated latency distribution. Raw probe source_manifest_sha256 is null and stays unchanged; immutable binary identities and a final retrospective source manifest are separate evidence. MILLION_GATE.json binds raw hashes.

Four actual128MiB frozen resource cases completed4/4,0failures/errors/skips,0OOM; see resource-final/. Exact native b250 binary mounted read-only, using legacy explicit --dev-protocol adapter and unchanged frozen resource assertions. This is distinct from the separately tested defaultJSONL official20 and default-entry full-vector recovery. Kernel peak may touch128MiB; completion is not a memory-headroom claim.

NAT/shared-IP night instability delayed SSH state retrieval; completed probes were not rerun. Remaining publication steps: final independent audit, current source/material/evidence binding, normal personal branch commit/push. No formal assessment or shared-branch merge.
