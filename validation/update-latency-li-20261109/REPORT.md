# MiniVectorDB V2 UPDATE investigation on Linux cloud server

Date: 2026-11-09. Branch: `perf/update-latency-li-20261109`. Base commit: `e5093aec5ce443d863a92a684eae7ed8f90a736e`.

## Decision and unresolved issue

Keep production V2 unchanged. This server reproduced an isolated UPDATE+SELECT slow sample, but did **not** reproduce the historical consistent three-pair ~2x slowdown. The original cause remains unresolved. No production fix or new production candidate is claimed. Removing persistence, weakening atomicity, changing results, or making a speculative tree optimization would not be justified by this evidence.

This commit adds reproducible investigation tools, independent new measurements, test logs and real learning records. B, production V2 and instrumented diagnostic executables are explicitly separate objects. All historical evidence remains byte-for-byte unchanged.

## Version and environment checks

`HANDOFF.md` and its five required documents were read. Handoff verification passed all 13 production files, 49 old audit files and 320 cardinality evidence files. The baseline ZIP member names and modes were checked before extraction; its 12 production files matched the B manifest. The clean handoff commit was fetched as a shallow repository through the existing deployment identity; shallow history does not omit the historical evidence files stored in this commit. Interrupted transfer data is retained outside the repository under `/home/li/minivectordb-v2-work`, not treated as validation.

Ubuntu x86_64, Linux 6.8.0-48-generic, 4 CPUs, 7.8 GiB RAM, no swap, GCC 13.3.0, CMake 3.28.3, Python 3.12.3, NumPy 1.26.4. Full details: `environment.json`. Native Release rebuilt both versions with the same configuration; both binary hashes exactly match the historical objects:

| Object | Production tree SHA-256 | Local Release binary SHA-256 |
|---|---|---|
| B | `42affed2e283c8710151931f6f419eee64210eda42245be6d357dc20ae520bb2` | `747092fd68833b52ec80020e050d4586d443220f513d6b3d932ab3e25eea072f` |
| V2 (also final production) | `df56a37dcbae572b6283dfd4ee67cccc1e7e15f2117b59760cf7628936ae18f3` | `78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c` |

Runtime image and build log are recorded separately. The image installs the C++ runtime on a digest-pinned Ubuntu 24.04 base; exact image ID and package versions are in `runtime-image.json` and `runtime-build.log`. The exact B/V2 native binary is mounted read-only. This is not a claim that the production Dockerfile was independently rebuilt.

## Original-history paired reproduction

Frozen historical `paired_benchmark.py` and its adapter/oracle were executed with explicit local paths, current runtime image, standard Docker socket, CPU set 0,1, 2 CPU quota, `memory.max=134217728`, `memory.swap.max=0`. Runtime limits were read back from real cgroups. No shared Docker service was started or stopped, no global caches were dropped, and no unrelated containers were modified.

Three independent alternating pairs per workload: B→V2, V2→B, B→V2. Every run used a fresh database directory and rebuilt data from the original writes. Million-row cases used 1000-row autocommitted batches, all original primary-key probes, first scan plus three warm scans, and for vector4 the first plus three warm filtered vector TopK queries, before the single-row UPDATE and SELECT. Subsequent mutations, transaction operations and crash/restart probes were also run. The complete decompressed SQL bytes of all three archived workloads match the historical saved gzip workloads; hashes are in `RESULTS.json`. Loading a final WAL was not used as a substitute for write history.

All 18 runs passed their correctness and resource-health checks. The 6066 vector128 responses were independently checked against the FP32/FP64 reference, including filtered and unfiltered queries. High-cardinality checks cover all issued responses, independent expected TopK, acknowledgements and specified recovery probes; they do not dump all recovered million rows.

### UPDATE plus primary-key SELECT (milliseconds)

| Workload | B rounds | V2 rounds | Paired B/V2 median |
|---|---|---|---:|
| scalar 1m | 5.136, 4.033, 6.328 | 2.639, 9.917, 4.042 | 1.5655 |
| vector4 1m | 3.647, 4.511, 3.353 | 2.929, 15.632, 3.096 | 1.0832 |

The vector4 V2 sample of 15.632 ms is a real negative observation and is retained. It was slower than its paired B sample by ~3.46x, while the other two pairs were faster. These three pairs neither explain the historical consistent ~6→13 ms result nor prove that the latency issue is fixed. Pair order is only partially balanced, the sample count is small, and cloud hardware/storage and host scheduling differ from the original WSL environment.

### Other timing and memory results

| Metric | B median | V2 median | Paired B/V2 median |
|---|---:|---:|---:|
| 10k×128 write, s | 0.9385 | 0.9193 | 1.0105 |
| 10k×128 1000 warm queries, s | 3.0306 | 2.8906 | 1.0204 |
| 10k×128 restart to first response, s | 0.2685 | 0.2820 | 0.9317 |
| scalar 1m write, s | 8.3298 | 8.2516 | 1.0182 |
| vector4 1m write, s | 8.9401 | 9.7916 | 0.9108 |
| scalar 1m main sampled anon, bytes | 72,232,960 | 40,271,872 | — |
| vector4 1m main sampled anon, bytes | 73,256,960 | 41,279,488 | — |

The compact-index anonymous-memory benefit remains approximately 32 MB for both million-row schemas. This is not a claim that total container memory halves. Kernel memory.peak, sampled anon/file, events and raw io.stat are all preserved separately in run.json and summary.json; maxima of different components need not occur together.

Vector4 writes regressed in all three pairs: paired V2/B median about 1.0980 (~9.8% slower). The 10k×128 restart paired median is about 7.33% slower. Every negative-median timing metric, including smaller stages, is listed in `RESULTS.json` and `paired-original/summary.json`; none is dropped. B/V2 ratios are computed per pair and then summarized, not inferred from division of independent medians. These are measurements of the unchanged versions on this host, not gains caused by this investigation.

## Separate diagnostics and root-cause boundary

`diagnose_update.py` byte-checks the entire archived vector4 SQL history and executes the complete original prefix through UPDATE+SELECT, then separates SQL send, wait/read, JSON consumption and total time. It records real cgroup CPU/resource snapshots and verifies all issued acknowledgements and expected rows. Separate default-binary runs are in `diagnostic-split-*`; separate strace runs in `diagnostic-trace-*`; instrumented-main runs in `diagnostic-instrumented-*`. All six runs passed the issued-result checks.

| Single diagnostic observation | B | V2 |
|---|---:|---:|
| default-binary UPDATE client total, ms | 2.339 | 3.500 |
| default-binary SELECT client total, ms | 0.394 | 0.576 |
| traced UPDATE fdatasync, ms | 1.691 | 1.515 |
| instrumented UPDATE engine, ms | 1.744 | 1.503 |
| instrumented UPDATE serialization, μs | 10.790 | 9.990 |
| instrumented UPDATE flush, μs | 14.662 | 13.627 |
| instrumented SELECT engine, μs | 43.421 | 40.564 |

These rows come from **different fresh runs** and must not be added or subtracted to manufacture a single decomposition. Each mode has one B/V2 observation, not a distribution or a final performance result. Tracing changes scheduling and syscall costs; main instrumentation adds clock reads and stderr logging. Production src/main.cpp and default binaries are untouched. Diagnostic executables link the corresponding frozen B/V2 library, and have separately recorded hashes.

Both traced UPDATE paths performed the expected row/metadata reads, WAL writes, one successful fdatasync, and complete responses of identical byte counts. The initial blocked stdin read includes the deliberate trace-attachment idle period and is not database execution time. The sampled diagnostic calls show real synchronization waiting, but did not capture the 15.632 ms slow case. They therefore do not establish fdatasync, the compact tree, response serialization, CPU quota, Python GIL or the sampler as the cause of that case or the historical regression. The historical sampler on/off negative result is retained unchanged.

No source fix was attempted because no reproducible production defect was established. Next useful experiment: capture syscall and scheduler timing on an occurrence of the slow tail under the same complete history, with a larger predeclared balanced sample count and host-contention observations. Avoid replacing current evidence with selected favorable rounds.

## Local regression scope

Initial native Release: CTest 5/5; blackbox 18 pass + 1 stress skip; extra regression 8 pass + large-output class skip. Expanded native Release: blackbox 19/19 and extra regression 11/11, no skips. This includes transaction/reference-model/cache/error-output behavior; CTest includes the storage crash/checkpoint boundary suite.

Final sanitizer, real-cgroup regression and bidirectional recovery results are recorded in `VALIDATION.md` after execution. Historical passes are not counted as local execution. Detailed logs remain the authority for failures/skips.

## Official references and remaining limitations

See `official/SOURCES.md` for the two user-provided official URLs and their discrepancy about the default final submitted version. Full downloaded reference documents are retained only on the server, with hashes, rather than republished in Git. agent/conversation.json remains truthful and distinguishes user, agent and tool evidence; no student understanding or unperformed experiment is invented.

Not completed: root cause of the original stable UPDATE regression or this host's isolated slow sample; official stdin/stdout adapter and complete official tests; calibrated dedicated-device physical I/O/writeback attribution; a fresh build of the production Dockerfile; ANN; 2m capacity ladder on this host; real power loss/media faults. First-process reads are not OS-cold-cache measurements. Shared-host cloud contention and the small repeat count limit attribution. The index still has O(N) resident memory and arena high-water retention.

No official assessment, scoring run, score prediction, force-push or modification of another branch was performed. Database directories remain on this server but are excluded from Git; SQL, expected/actual results, commands, scripts, hashes and observations are committed. The final evidence manifest detects changes; it is not a third-party signature.
