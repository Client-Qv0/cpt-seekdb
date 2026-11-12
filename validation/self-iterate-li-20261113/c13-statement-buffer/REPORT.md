# C13 statement-level journal buffering — successful

## Result

Retain this change as successful performance commit 3/5.

C13 buffers journal frames for the active statement and flushes at a bounded 1 MiB threshold or when the statement finishes. A normal 100-row INSERT now reaches the journal through one positional write instead of roughly one `pwritev` per row.

The target write metric improved by a **6.755% median with 5/6 wins** over the immediate parent. Data file bytes were identical and peak process RSS median changed by -1.105%, inside the 2% limit. Query code was not changed; its +1.520% median was not used as the retention gate.

## Correctness design

- Frames remain byte-for-byte header + table + value at the original absolute offsets.
- Reads of current-statement refs are served from the pending buffer before the bytes are flushed.
- At the 1 MiB threshold, buffered bytes flush once and subsequent refs remain readable from their new buffer or file segment.
- Statement abort clears the buffer and truncates any flushed portion to the pre-statement offset.
- Statement finish flushes all buffered data before transaction overlay or commit-marker publication.
- The commit marker is still written directly and followed by `fdatasync`.
- Transaction visibility, rollback, normal shutdown rollback, SIGKILL recovery, every-byte commit truncation and checkpoint boundaries retain their previous semantics.
- Destructor recovery remains bounded by the durable commit offset.

The dedicated test covers update-in-progress readback, scan visibility, abort, a >1 MiB statement crossing the flush threshold, transaction readback and rollback.

## Syscall evidence

A 1,000-row write-only diagnostic produced:

| Version | `pwrite64` | `pwritev` | `fdatasync` | Traced total |
| --- | ---: | ---: | ---: | ---: |
| C12 immediate parent | 1 | 1,012 | 13 | 1,026 |
| C13 | 12 | 11 | 13 | 36 |

The remaining calls are initialization, ten statement flushes, commit markers and checkpoint metadata rather than one write per row.

## Validation

- Targeted storage suite: `10` suites passed.
- Release CTest: `7/7`.
- ASan/UBSan CTest: `7/7`.
- Acceptance with stress: `21/21`.
- Optimization and large-output: `16/16`.
- Public bridge: `4/4`.
- Native official public cases: `20/20` cases, 95 SQL.
- Official fixed Docker public cases: `20/20`.
- Docker image binary SHA-256 equals native binary SHA-256:
  `4784016c18bd29ddaa282f73944af1ad2a6425abb6b34dbdea90153001a0349e`.

## Artifacts

- `ab/`: six raw pairs and summary.
- `strace-candidate.txt`: syscall-count evidence.
- `final-test-run.log`, `final-ctest.log`, `final-sanitize-ctest.log`.
- Acceptance, optimization, native public and official Docker results.
- Image/binary hashes and Docker build log.

These are local shared-host measurements, not an official score. Physical-I/O accounting, the official baseline and hidden cases remain unavailable.
