# Local validation, 2026-11-09

All rows describe executions on this server, not historical test passes.

| Configuration / test | Result | Evidence |
|---|---|---|
| V2 Release CTest | 5/5, zero failed | ctest-release.log |
| B Release CTest | 4/4, zero failed | ctest-baseline.log |
| V2 expanded Release blackbox | 19/19, zero skips | acceptance-release-full.log |
| V2 expanded Release extra regression | 11/11, zero skips | optimization-release-full.log |
| V2 ASan/UBSan CTest | 5/5, zero failed | ctest-sanitize.log |
| V2 ASan/UBSan blackbox | 18 pass; 1 storage-pressure test skipped | acceptance-sanitize.log |
| V2 ASan/UBSan extra regression | 8 pass; large-output class skipped | optimization-sanitize.log |
| Actual 128 MiB cgroup large-output/storage | 4/4, zero failures/errors/skips; no container OOM | resource-regression/ |
| B/V2 WAL/checkpoint compatibility | both directions pass; full 1000 initial/999 modified rows including vectors | index-compatibility.json |
| Original-history paired workloads | 18/18, all independent result/resource checks pass | paired-original/ |
| Separate diagnostic history replays | 6/6, all issued acknowledgement/row checks pass | diagnostic-*/run.json |
| Immutable handoff evidence | 13+49+320 files, zero mismatches after all tests | handoff-verify-after.txt |

ASan/UBSan uses Debug, -fsanitize=address,undefined -fno-omit-frame-pointer; leak detection and halt-on-error enabled. No sanitizer error was reported in executed suites. Stress/large-output success under Release/cgroup does not imply sanitizer coverage of skipped cases. Logs identify their exact scopes.

All resource tests read back memory.max=134217728, memory.swap.max=0, cpu.max=200000 100000. Their cgroup peak values are recorded below; completion does not imply ample memory headroom. io.stat is raw shared-device observation, not calibrated official physical I/O.

| Resource process | memory.peak bytes | Exit code | OOMKilled |
|---|---:|---:|---|
| storage/setup/restart | 134217728 | 137 | False |
| __main__.ContainerLargeResponses.test_distance_topk_with_large_payload_exceeds_heap_budget | 134217728 | 0 | False |
| __main__.ContainerLargeResponses.test_large_limit_multikey_order_spills_without_changing_order | 134217728 | 0 | False |
| __main__.ContainerLargeResponses.test_no_limit_select_star_streams_beyond_memory_budget | 134217728 | 0 | False |
| storage/setup/restart | 4583424 | 137 | False |
| storage/setup/restart | 134217728 | 137 | False |
| storage/setup/restart | 83996672 | 137 | False |

Requested SIGKILL in storage recovery can produce 137 without OOM. Resource driver assertion logic remains the frozen four-case harness; path, socket, runtime image and evidence metadata were adapted in resource_driver.py. The existing Docker daemon was reused and remains running.

Production candidate remains byte-identical to V2; no new source fix or official assessment is claimed.
