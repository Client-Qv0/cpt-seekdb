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

Local performance-shape and persistence validation:
  python3 -m pip install numpy
  docker build -t minivectordb-local .
  cid=$(docker create minivectordb-local)
  docker cp "$cid:/app/minivectordb" ./build/image-minivectordb
  docker rm "$cid"
  python3 tests/benchmark_public_validation.py \
    --binary ./build/image-minivectordb --image minivectordb-local \
    --source . --manifest validation/cardinality-20261109/candidate-v2-production-manifest.json \
    --output ./validation/my-new-benchmark-run --data-parent /var/tmp \
    --seed 3179 --rounds 3

The parent directory for database files must be local Linux ext4 and the output
directory must not already exist. This requires NumPy, Docker, cgroup v2, access
to the container host's /proc and /sys/fs/cgroup, and at least two allowed CPUs.
It uses 2 CPUs, 128 MiB and no swap for local testing; those are not asserted to
be official limits. The source manifest must match the production inputs under
test. The extracted binary is checked against the binary inside the exact image.
The harness retains inputs, per-query oracle checks, responses, cgroup samples,
and a full post-restart readback. Database files remain in a task-specific
directory below --data-parent and are not removed by the harness.
The local seeded generator and JSON-lines development adapter are not the
unpublished official generator or process protocol. Shared-device io.stat and
this output cannot establish an official score or rank.

The optional stress case writes 192,000,000 bytes of payload to a database
process with a 128 MiB address-space limit and reopens it under that same limit.
This is a local bounded-memory storage check, not the organizer's cgroup v2
memory.peak / disk-I/O performance measurement.

Startup-interruption checks do not include a hook inside recovery and therefore
cannot guarantee that each signal arrives during replay. The lost-response
commit check permits either the whole transaction or none of it, as the task
specifies. Index checks currently verify exact-mode maintenance semantics only;
ANN mode and the final stdin/stdout contract await the official problem package.
