# Exact-query work package progress

Base: 75ecbf3e60a68de7d833aa899bc0fcb4c48df47e. Remote isolated worktree: /opt/minivectordb-v2-query; personal branch perf/exact-query-li-20261109.

- [x] Fetch official public package at immutable 9f6df2ba5acf871376e22b64a3d0724e4b575044; verify downloaded Git blob identities.
- [x] Local bridge assertions tested red (missing module), then four targeted tests green: unordered rows, duplicate preservation, exact BIGINT and floating tolerance.
- [x] Baseline V2 public20/95 pass. ANN directive explicitly uses existing exact fallback, not ANN implementation or official transport coverage.
- [x] Production Dockerfile no-cache build and actual Docker-entry public20/95 pass; image executable SHA256 78996ec9a6d15c5357b5111a4fd78ed28bf1cde174538dee81ae5de1b2daf26c matches frozen V2. Runtime package/image metadata saved.
- [x] Query decomposition, two engine pruning prototypes, standalone columnar component. Neither engine prototype meets20% gate; default production restored. Columnar Engine integration remains future work.
- [x] Two paired experiments, two additional seeds, Release/sanitizer,128MiB resource and million-row memory checks completed.
- [x] Primary review, report, manifests and truthful learning record finalized. Confirmed commit/push SHA is supplied separately in the delivery message.

All work remains development-only. Public case success is not official29-case admission. New public-package assertions do not define official process framing. The public runner requires nonempty error codes where final semantic mapping is not frozen.
