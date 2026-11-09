# HMY SQL safety revision: server takeover and fresh validation

Date: 2026-11-09. Upstream competition head verified as d85b5061d2e6aa12fd0d7bcedf7b493a695c40c0. Personal branch: perf/hmy-takeover-li-20261109. Source workspace: /opt/minivectordb-hmy-li. No official assessment.

## What was taken over

Read HANDOFF_HMY_20261109.md and the local/benchmark reports. The teammate fixed unsafe double-dash comment tokenization, including statement/transaction/restart regressions. Compared with our previous handoff944c08e, production changes are concentrated in src/sql.cpp; the new tests and validation tools are also adopted. We did not merge the old handoff branches again, revert the teammate's fix or claim authorship of it.

The production source is unchanged relative to d85b506. This round corrects tests/README.txt and adds fresh evidence. The parser's new binary must not inherit the old78996ec9 performance identity.

## Transfer and evidence limitations

The first full Git fetch was very slow because new archived full-readback results are large. It was stopped; partial transfer files outside this checkout are not validation. A filtered fetch and sparse checkout then obtained the exact commit, source, tests, current parser evidence and required reports. The repository remains a promisor/partial checkout; source/test coverage is complete for the executions below, but we did not download or independently audit every large new HMY historical benchmark artifact. The old716 manifest entries (49+320+141+206) were all materialized and verified unchanged. On arrival,33 selected source/test/agent/handoff Git blobs matched the pinned upstream tree, excluding the intentional README edit. A real learning record was appended afterwards and separately validated. git-blob-verification.json records these paths.

Official oceanbase/seekdb competition tree was checked again:9f6df2ba5acf871376e22b64a3d0724e4b575044. It still exposes public20/95 cases without a complete formal transport driver. This is an observed interface gap, not permission to guess the final protocol.

## Fresh server validation

Current production manifest:13 files; tree SHA256 dffe88f3275f16bfcae27a13277383efc925587f767dfbbf051b5ef7b2bf45ef.
Native Release and executable extracted from a fresh no-cache production Dockerfile build are both:

ffe90b07f75fbb8b38ddf225b5e04176318d3f46614e5a195c646b18314aae4d

This exactly matches the teammate's reported build, but the following results were actually rerun on this server:

| Check | Result |
|---|---|
| Release CTest |5/5 pass|
| Release blackbox, stress enabled |21/21 pass, including double-dash safety and persistent autocommit regression|
| Release extra regression, large enabled |14/14 pass|
| Public bridge unit tests |4/4 pass|
| Native public cases |20/20 cases,95/95 SQL|
| Actual image ENTRYPOINT public cases |20/20 cases,95/95 SQL|
| Agent material checks |5/5 pass before this round's record, rerun after append|
| Full-readback validator unit tests |2/2 pass|
| ASan/UBSan CTest |5/5 pass|
| ASan/UBSan blackbox |20 pass,1 address-space pressure test skipped|
| ASan/UBSan extra regression |11 pass; large-output class separately skipped|

No sanitizer error reported in executed suites. Skipped pressure/output cases were run under Release, not represented as sanitizer coverage. Docker build uses the unchanged mutable Ubuntu/apt recipe; successful no-cache construction and exact current binding do not lock future dependencies. Prior OpenSSL/snapshot probes were not copied into the runtime, and TLS verification was not disabled.

## Post-fix performance and persistence baseline

Ran the teammate's tests/benchmark_public_validation.py without production or driver modification. It checks actual image binary against the supplied executable, production inputs, real2CPU/128MiB/no-swap cgroups, every query against an exhaustive FP32/FP64 oracle, then starts separate containers to read and verify every10,000 persisted rows and all128 components.

Seed3179, three predetermined rounds, each from an independent empty database. No sanitizer build or other task test workload ran during these three measurements. Shared host/cloud contention is not eliminated. The workload shape is local10k×128,100 batches of100 rows,1000 hot Top10 queries,500 filtered; it is not the unpublished official generator.

| Round | Write seconds |1000 hot query seconds|Main memory.peak bytes|
|---|---:|---:|---:|
|1|0.983571|2.996172|14,118,912|
|2|0.973997|2.810922|14,135,296|
|3|0.945787|2.861128|14,036,992|
|Median|0.973997|2.861128|14,118,912|

All3 rounds completed, tools unchanged,1011 result sets per round independently checked (first/warm-up plus timed queries). Filtered/unfiltered minimum and average Recall@10 were1. Every round's separate restart verified all10,000 rows and every stored FP32 component. Main containers reported no OOM or memory max event.

Seed9143 added one correctness-only round, also passing query oracle and full readback. It overlapped later sanitizer/public-case verification; its recorded timings are NOT included in performance medians or used for comparison. Four rounds total provide4044 independently checked query responses and four full10k readbacks. Tool hashes, actual image/source binding, responses, expected results, raw cgroup measurements and complete readback gzip files are retained.

The teammate's WSL query median about1.186s belongs to another environment and old executable. Comparing it with2.861s here cannot establish a parser performance regression. This round does not include a contemporaneous alternating old-V2 control, so it makes no causal speedup/no-regression claim about the parser fix. These new values establish a post-fix local baseline only.

Raw io.stat is retained on the shared ext4 device, with no dedicated-device calibration, uniform OS-cold cache procedure or final writeback accounting. No officialB/E,score,40-point result or rank is computed. First query is process-first, not OS-cold.

## README correction

The copied benchmark example referenced validation/cardinality-20261109/candidate-v2-production-manifest.json. That old manifest identifies the old parser, so current source verification would fail. The example now generates a current13-input manifest in an ignored build directory, freezes it across the build/run, and passes that file instead. Historical manifests are never rewritten. The exact inline generation code was executed and its output equals production-manifest.json in this new directory. Temporary extraction container cleanup now uses docker rm -v for only its own anonymous volumes.

## Remaining work and next step

- Formal transport, error mapping and complete29-case admission still unverified; public20/95 success and ANN's explicit exact fallback are not substitutes.
- Production Docker dependencies remain unlocked; a real pinned build must validate source/image/versions/TLS/signatures and independently rebuild, not promote the old probe's OpenSSL packages blindly.
- Engine columnar-cache integration still unimplemented; current frozen standalone probes do not prove cache invalidation, transaction behavior, strict memory or end-to-end gains. With the corrected post-fix baseline established, that is the next performance work item: profile execution stages and implement one-budget replacement plus generic fallback and independent tests before adopting it.
- UPDATE tail latency remains unexplained. Do not remove sync or preselect a cause. Reproduce complete original write/query history before any fix.
- This round did not rerun the separate four-case128MiB large-output cgroup harness, the2m ladder, or bidirectional checkpoint helper. Release large-output and actual128MiB benchmark/restart tests are different scopes. Prior evidence remains historical.
- No production code optimization was added in this takeover; no official submission or force-push. The competition branch is untouched. New data remains in task-owned /var/tmp directories and is not committed; complete result/SQL/readback evidence and hashes are committed.
