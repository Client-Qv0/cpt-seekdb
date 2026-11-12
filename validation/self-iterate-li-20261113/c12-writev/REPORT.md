# C12 journal frame `pwritev` — successful

## Result

Retain this change as successful performance commit 2/5.

Each journal frame was previously written with three separate `pwrite64` calls: the 32-byte header, table name and value. C12 writes those same three ranges with one `pwritev` call while preserving the exact frame bytes, offsets, partial-write retry loop, commit marker, `fdatasync` durability point and crash recovery semantics.

The target write metric improved by a **6.648% median with 6/6 wins**. Query time is unchanged by this write-only code path and measured a +1.187% median in the same pairs. Peak RSS and data file bytes did not regress.

## Syscall evidence

A 1,000-row diagnostic under `strace -f -c` measured:

| Binary | Frame writes | `fdatasync` | Measured syscall time |
| --- | ---: | ---: | ---: |
| Base C7 | 3,015 `pwrite64` | 13 | `0.023831 s` |
| C12 | 1,012 `pwritev` + 1 `pwrite64` | 13 | `0.006703 s` |

The one remaining `pwrite64` is unrelated to per-row frame construction. The journal file size was byte-identical in all six paired runs.

## Correctness

- `writev_all` retries interrupted and partial `pwritev` operations across iovecs.
- The existing format remains header + table + value at the same positions.
- Statement failure still truncates to its pre-statement offset.
- Autocommit still publishes durability only through the commit frame plus `fdatasync`.
- Transaction rollback, shutdown rollback, SIGKILL recovery, every-byte commit truncation and recovery interruption remain covered.
- Checkpoint crash injection now recognizes both `pwrite64` and `pwritev`, including BeforeWrite and DuringWrite boundaries.

## Validation

- Targeted storage suite: `9` suites passed, including commit truncation, recovery interruption and checkpoint crash boundaries.
- Release CTest: `7/7`.
- ASan/UBSan CTest: `7/7`.
- Acceptance with stress: `21/21`.
- Optimization and large-output: `16/16`.
- Public bridge: `4/4`.
- Native official public cases: `20/20` cases, 95 SQL.
- Official fixed Docker public cases: `20/20`.
- Docker image binary SHA-256 equals native binary SHA-256:
  `f9b8fc09aa0c0a9ec78755b32c5cc99bc5e951d91d11f776c9cbd2ffc0dea431`.

## Performance method

Six immediate-parent pairs alternated base-first and candidate-first under fresh 2-CPU, 128-MiB and zero-swap transient cgroups. The base is retained commit 1, `7168a6476697141ea9afc86c11e8bc4e5297be92`.

## Artifacts

- `ab/`: six raw pairs and summary.
- `strace-base.txt`, `strace-candidate.txt`: syscall-count evidence.
- `ctest.log`, `sanitize-ctest.log`: Release and sanitizer matrices.
- Acceptance, optimization, native public and official Docker results.
- Image/binary hashes and Docker build log.
- Reproduction scripts.

These are local shared-host measurements, not an official score. Hidden generator, official baseline and physical-I/O accounting remain unavailable.
