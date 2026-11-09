# Local development verification — 2026-11-09

Status: **development milestone, not ready for official submission**.
Base branch: `2026-competition-round2`.
Official base commit: `c842a368c3394748d0499386c18f6b465242e141`.
These changes have not been pushed or submitted for assessment.

## Environment and checks

Local Ubuntu 24.04 under WSL, GCC 13.3.0, CMake 3.28.3, Python 3.12.3.
Native Linux build; Docker is unavailable on this host and image execution has
not been verified. The local environment is not the frozen evaluation machine.

| Check | Observed outcome |
|---|---|
| Release build | Successful |
| Parser tests | 68 checks passed; checks execute with NDEBUG |
| Extra engine tests | 30 checks passed, including the VARCHAR comparison regression |
| Storage tests | 6 suites passed: transactions, statement rollback, process termination, commit-tail truncation, locking and observed recovery interruption |
| Black-box acceptance | 18 ordinary tests passed, including a 140-step independent reference model |
| Bounded-address-space test | 192,000,000 payload bytes written, process killed, reopened and queried with a 128 MiB RLIMIT_AS |
| ASan + UBSan | All 3 CTest suites and all 18 ordinary black-box tests passed; no sanitizer finding reported |

RLIMIT_AS does not measure container memory including page cache. The stress
result is not evidence of passing the official cgroup resource limits. The
black-box startup-interruption test does not locate the kill within recovery.
The separate storage suite uses ptrace to observe journal reads past 1 MiB,
interrupts recovery twice, and checks the 64 MiB committed payload afterward;
this final test also passed under ASan/UBSan, without production test hooks.

## First local timing baseline

`tests/benchmark_local.py`: 10,000 rows, 128 dimensions, 1,000 exact Top-10
queries; half the queries include a scalar filter. One measured run:

* Batched auto-committed inserts: 0.689805873 seconds.
* Query sequence: 4.660568560 seconds.
* Data files: 5,633,351 bytes.

The raw result is in `local-benchmark.json`. Dataset generation is outside the
timing window. There is no official baseline ratio, cgroup I/O measurement,
container memory peak, three-round ranking statistic or score prediction.

## Remaining work before a submission recommendation

1. Implement and verify the exact official input/output adapter and error codes.
2. Finish index acceleration and any required ANN interface; current index DDL
   persists metadata but uses exact scans for execution.
3. Bound large-result memory with streaming/external sort, and validate long
   update histories, recovery resources and log reclamation.
4. Build and run the Docker image in the frozen environment; pin dependencies.
5. Run the official public tests, preflight and resource benchmark.
6. Continue preserving genuine student learning evidence. Current agent-generated
   implementation and tests do not demonstrate the student's own understanding.
7. Verify the pushed commit equals the tested source and explicitly choose the
   final assessment version. Do not rely on conflicting default-version rules.

The official protocol and hidden cases are not simulated by declaring the local
JSON adapter to be the competition interface. No full-score claim is made.
