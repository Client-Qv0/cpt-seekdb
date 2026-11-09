# MiniVectorDB local handoff and columnar experiment (2026-11-09)

## Decision

Keep the default V2 production files unchanged. The isolated columnar Engine prototype in `prototype-engine.cpp` did not meet the pre-existing 20% warm-query engineering target and has not established a strict peak-memory budget. It is evidence for further work, not an accepted implementation. It has one ordinary scalar filter column, handles no filter or scalar equality, stores FP32 vectors contiguously, and falls back to the generic scan for unsupported predicates/schemas or rejected capacity. It does not implement postings or ANN, and it does not modify the WAL.

The prototype makes two scans to build the cache. Its 64 KiB admission slack is not a proof that allocation metadata and the largest transient decoded row fit the total budget; allocation failure is not explicitly converted to fallback. These and its observed performance rule out production promotion. Existing non-mutating SELECT fallbacks and write/transaction invalidation were exercised, but no independent review approval is claimed. The old UPDATE latency root cause remains unknown and was not investigated in this round.

## Identity and environment

- Windows worktree `E:/MiniVectorDB/work`, branch `codex/minivectordb-hmy-20261109`, based on `944c08ee3549a625706801565fe570d804e58928`. The only commit from `08e5f5518fd6583189d34072bb2af40447d7a6a5` to that HEAD is the newer handoff document; `src`, `Dockerfile` and `CMakeLists.txt` match the latter commit.
- WSL2 Ubuntu x86_64, GCC 13.3.0, CMake 3.28.3, Python 3.12.3, NumPy 1.26.4. Downloaded tools live under `E:/MiniVectorDB/deps`; build trees are under `E:/MiniVectorDB`. Full environment is in `environment.txt`.
- Release control binary SHA-256 `78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c`. Prototype Release binary SHA-256 `e73cf5f917e6fbb2320b7a4a690ff38a272a27d5f2258aabbd38ff1544763d73`; prototype engine SHA-256 `b2be4b6c23def0202e592e4c898d6babc50b26b3682b2ee87e58095234ae72f5`.
- The Windows Git worktree's `.git` file contains a Windows path; invoking Linux Git in WSL directly on this worktree fails to resolve it. Use Windows Git for its status/diff. This does not affect building or running the Linux binaries.
- Read-only old manifests verified 13 + 49 + 320 + 141 + 206 files, all zero failures; old learning material hash matched before this round's truthful append. See `handoff-verify.txt` and `evidence-verify.txt`. No old finalize script was run.

## Local tests

| Test | V2 control | Isolated prototype |
|---|---|---|
| Release CTest on Linux tmpfs | 5/5 | 5/5 |
| Public bridge unit tests | 4/4 | not repeated separately |
| Public package bridge | 20 cases / 95 statements | 20 cases / 95 statements |
| Release acceptance | 19/19 including stress | 18 pass, 1 stress skipped |
| Release optimization acceptance | 12/12 with `--large` before new tests; later 11 regular tests pass, large class skipped | 11 regular tests pass, large class skipped |
| ASan/UBSan CTest | 5/5 | 5/5 |
| ASan/UBSan acceptance | 18 pass, 1 stress skipped | 18 pass, 1 stress skipped |
| ASan/UBSan optimization | 9 regular tests pass, large class skipped; before the final two tests were added | 11 regular tests pass, large class skipped |

The new checks use a separate Python FP32-quantized / FP64 distance reference across seeds 9143, 27183 and 3179 and dimensions 1, 3 and 17; they compare IDs, order and distances, equality/range/empty filters, ties and repeated reads. Additional tests exercise string filters, failed statements, rollback, commit, restart, and 3,100 vectors of dimension 1,024 that exceed the cache budget. They run against both control and prototype; the larger reference test uses repeated zero vectors and does not prove every boundary. The fixed 10k × 128 benchmark below independently checks its original seed; no additional 128D performance seeds were run.

The first control CTest run used E: as `TMPDIR` and failed spill on `ftruncate` of an unlinked temporary file; the other four suites passed. It is preserved in `ctest.txt`. On Linux tmpfs the repeat passed all five (`ctest-linux-tmp.txt`). This shows a filesystem-dependent failure on this machine; it is not evidence that Windows-mounted storage supports the spill path. The baseline stress and large-output tests ran on tmpfs under RLIMIT_AS; they are not replacements for a physical-device cgroup test.

## Profile and paired experiment

The standalone diagnostic source and binary differ from Release. On 1,000 retained 128D queries, explicit timers observed 1,000 parses, 10,000,000 filter calls, 6,010,000 distance calls (including winner projection) and 6,000,000 heap checks. These measurements include timer overhead on each row and cannot be summed into an uninstrumented performance score. Instrumented output matched the separate gprof-build output byte for byte. `gprof.txt` has implausible symbol attribution due to optimization/inlining and is retained as a failed diagnostic, not as proof that JSON serialization dominates.

The comparison used newly built local control and candidate binaries, three predetermined alternating pairs, separate data directories, 2 CPU quota, 128 MiB memory and swap disabled. `docker-cgroup-check.json` confirms that the Docker container PID and cgroup can be read from this WSL instance, including actual limits; a fresh scratch runtime image was built from the local runtime libraries with no network. Actual binary hashes, inputs, output, oracle checks and sampled cgroup data are in `paired-output/`. The control lock and candidate manifest were generated for these local binaries. The original harness was copied with its filesystem check extended to allow tmpfs; no old script or manifest was overwritten.

| Pair order | V2 warm queries (s) | Prototype (s) | Prototype time change |
|---|---:|---:|---:|
| V2, prototype | 1.238757 | 1.198919 | −3.22% |
| prototype, V2 | 1.132450 | 1.340345 | +18.36% |
| V2, prototype | 1.225005 | 1.281727 | +4.63% |

All six paired runs passed the existing independent oracle checks, including IDs, order, distances and filtering, with unchanged binary/source identities. First-query time was approximately 9.58–9.60 ms for V2 and 13.96–15.12 ms for the prototype. Each sampled main-container `memory.peak` ratio was approximately 0.88–0.90 candidate/control, but tmpfs placement and one small workload do not establish complete production memory savings or the cache's strict budget. Timings are local only; the pairing is not fully order-balanced and the host was not a dedicated evaluation machine.

The databases and evidence were initially produced on `/dev/shm` to avoid E: filesystem semantics and C: downloads. Consequently the experiment cannot measure representative disk durability, physical I/O, or cgroup writeback attribution; no score is inferred. The first evidence copy attempted to copy container-owned DB files and reported permission errors. A corrected read-only copy retained 29 evidence files and omitted the reproducible database directories (`paired-copy.txt`); SQL, responses, oracle results and sampled resources are retained. The copy helper now propagates failure. The original temporary directories may disappear after reboot.

## Not done / next work

- True single-budget accounting including allocation headers, all temporary row buffers, and worst-case build peak; safe allocation-failure fallback; postings and broader eligible schemas.
- A convincing end-to-end speedup in the fixed paired protocol, held-out full 128D seeds, production-file candidate sanitizer/large-output/cgroup recovery testing, independent review, and million-row memory comparison. Prototype sanitizer results are recorded above; the prototype was not promoted.
- Real disk `io.stat` attribution, WSL host disk/cgroup writeback calibration, production Dockerfile rebuild/entrypoint validation, and official frozen benchmark configuration.
- Formal 29-case admission, official process driver/error mapping, actual ANN, official score, true power-loss testing, and the historical UPDATE slowdown diagnosis.
- No commit, push, force-push, or formal assessment was performed. `agent/conversation.json` only appends attributed, real excerpts and measured results; it does not claim student explanations.
