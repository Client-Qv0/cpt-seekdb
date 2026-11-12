# C17 sync-on-write autocommit — successful

## Result

Retain this change as successful performance commit 4/5.

For a statement below the 1 MiB buffering threshold, C17 appends the commit marker to the buffered frames and writes the complete sequence with one `pwritev2(..., RWF_DSYNC)`. The separate `fdatasync` is omitted because the successful write already carries the required durability flags. A statement that crossed the 1 MiB threshold uses the conservative path: flush remaining data, write the marker, then call `fdatasync` so earlier chunks are covered as well.

The target write metric improved by a **2.096% median with 5/6 wins**. Query code was unchanged and data bytes remained identical. Peak RSS did not regress materially.

## Durability design

- The commit marker is still the final frame.
- `RWF_DSYNC` is used only when all statement data and the marker are in the same unflushed buffer.
- A previously flushed large statement falls back to full-file `fdatasync`; no “last write syncs earlier chunks” assumption is made.
- Transaction COMMIT retains direct marker write followed by `fdatasync`.
- Statement abort, read-your-writes, commit truncation, SIGKILL recovery and checkpoint publication boundaries remain unchanged.

## Syscall evidence

A 1,000-row write-only diagnostic produced:

| Version | `pwritev2` | `pwritev` | `pwrite64` | `fdatasync` | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| C13 immediate parent | 0 | 11 | 12 | 13 | 36 |
| C17 | 11 | 0 | 1 | 2 | 14 |

The two remaining `fdatasync` calls belong to initialization/close behavior, not each autocommit statement.

## Validation

- Targeted storage suite: `10` suites passed.
- Release CTest: `7/7`.
- ASan/UBSan CTest: `7/7`.
- Acceptance with stress: `21/21`.
- Optimization and large-output: `16/16`.
- Public bridge: `4/4`.
- Native official public cases: `20/20`, 95 SQL.
- Official fixed Docker public cases: `20/20`.
- Docker image binary SHA-256 equals native binary SHA-256:
  `9aa8283238a2e9e513b8f25d621becb2680d7a5e8bdebfa78dff014f9614e84a`.

## Artifacts

- `ab/`: six raw pairs and summary.
- `strace-candidate.txt`: syscall-count evidence.
- Release/sanitizer/public/Docker logs and result JSON.
- Image and binary identities.

These are local shared-host measurements, not an official score. The hidden workload, physical-I/O accounting and official baseline remain unavailable.
