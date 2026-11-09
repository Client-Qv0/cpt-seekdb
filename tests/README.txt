MiniVectorDB local acceptance suite

Run in Linux, using Python 3's standard library:
  python3 tests/acceptance.py --binary build/minivectordb -v
  python3 tests/acceptance.py --binary build/minivectordb --stress -v

The executable must expose the explicitly development-only --dev-protocol
adapter. Each input line is one complete SQL statement; each output line is a
JSON object with boolean ok, plus rows/columns/affected or code/error. No READY
line is expected. This adapter and suite are not an official competition
protocol or mysqltest package. Passing these checks does not establish hidden
test acceptance, performance ranking, or eligibility to submit.

Coverage derives from the published task semantics: exact L2 on float32
storage, filtered TopK, deterministic primary-key tie breaking, Unicode
length/order, 64-bit integer precision, rejected unsupported SQL, SQL statement
atomicity, explicit transactions, graceful shutdown, acknowledged commit
durability under SIGKILL, unacknowledged commit atomicity, startup interruption,
and a randomized independent transaction/vector-query reference model.

The optional stress case writes 192,000,000 bytes of payload to a database
process with a 128 MiB address-space limit and reopens it under that same limit.
This is a local bounded-memory storage check, not the organizer's cgroup v2
memory.peak / disk-I/O performance measurement.

Startup-interruption checks do not include a hook inside recovery and therefore
cannot guarantee that each signal arrives during replay. The lost-response
commit check permits either the whole transaction or none of it, as the task
specifies. Index checks currently verify exact-mode maintenance semantics only;
ANN mode and the final stdin/stdout contract await the official problem package.
