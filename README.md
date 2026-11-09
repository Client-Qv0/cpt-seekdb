# MiniVectorDB — correctness-first development version

**Teammate handoff (2026-11-09):** start with [HANDOFF.md](HANDOFF.md).
The current implementation is V2; the authoritative local results are in
[the V2 report](validation/cardinality-20261109/REPORT.md). Historical reports
describe their own frozen versions. Run `python3 tools/handoff/verify.py`
before editing to verify the handoff's source and evidence bytes.

This branch implements a standalone, single-process database for the
`2026-competition-round2` challenge. It does not use seekdb, SQLite, RocksDB,
Faiss, VSAG, or another database/index engine to execute operations.

**Not ready for official assessment.** The official framing, result formatting,
error codes, readiness signal and exact/ANN mode controls have not been supplied.
The development adapter below is explicitly opt-in and is not an assertion about
the official protocol. Passing the tests here is not passing official cases.

## Build and run locally

Linux x86_64, C++17, POSIX file APIs, CMake 3.16+ and Python 3 for tests:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 tests/acceptance.py --binary ./build/minivectordb
./build/minivectordb --data-dir ./build/demo-data --dev-protocol
```

The local adapter accepts one complete SQL statement per input line, emits one
JSON result per line, and flushes each response. EOF closes the process; pending
transactions must not survive restart. Diagnostics go to stderr. Example input:

```sql
CREATE TABLE docs (id BIGINT PRIMARY KEY, category VARCHAR(32), embedding VECTOR(2));
INSERT INTO docs VALUES (1, 'database', '[1,0]'), (2, 'database', '[0,1]');
SELECT id, L2_DISTANCE(embedding, '[1,0]') AS distance FROM docs WHERE category='database' ORDER BY distance LIMIT 2;
BEGIN;
UPDATE docs SET embedding='[0,0]' WHERE id=1;
SELECT id, L2_DISTANCE(embedding, '[0,0]') AS distance FROM docs ORDER BY distance LIMIT 2;
ROLLBACK;
BEGIN;
DELETE FROM docs WHERE id=2;
COMMIT;
```

Restart with the same `--data-dir` to query committed records. For Docker:

```sh
docker build -t minivectordb:development .
docker run --rm -i -v minivectordb-data:/data minivectordb:development
```

No network listener or GPU is needed. The Dockerfile compiles from source.
Base-image digest and package versions still need to be frozen against the
official environment; a local native build does not validate the Docker image.

## Design and current boundaries

* The parser produces a typed syntax tree; execution validates schema and values.
  BIGINT values are parsed directly as signed 64-bit integers. VARCHAR limits
  count Unicode scalar values in valid UTF-8. Vectors are finite float32 values;
  Euclidean distances accumulate in double precision from those stored values.
* Record payloads remain on disk, with primary keys and record locations in
  memory. The log and transaction overlays provide read-your-writes and statement
  rollback. A successful commit requires a durable commit marker.
* Exact vector searches filter the visible records before selecting the best K.
  Distances and ordinary ORDER BY ties break on ascending primary key.
* `CREATE VECTOR INDEX` currently records index metadata; queries still use an
  exact scan. An accelerated index and the official ANN controls are unfinished.
* Large results use external sorting and streaming. Relevant 128 MiB cgroup
  regressions passed; these do not prove unlimited capacity or memory headroom.
* The journal supports checkpoint/compaction with crash-boundary tests. The V2
  key index uses a compact shared arena, but still consumes O(N) resident memory.
  Two million short records completed the tested stages under 128 MiB; larger
  capacity and other distributions remain unverified. UPDATE latency regression
  is the next investigation, not a claim of universal performance improvement.
* Unsupported SQL must error. NULL, joins, aggregates, expressions in assignments,
  nested transactions and primary-key updates are outside this implementation.

The real official driver and frozen resource limits are required before deciding
whether to submit. No official cases, rankings or full-score outcome are claimed.
