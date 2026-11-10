# MiniVectorDB — JSONL protocol implementation

**Protocol update (2026-11-10):** the default native and Docker entrypoints now
implement the published JSONL protocol at official commit
`f4d4e26653af823a7601668802f80e374ad6643c`. The implementation is based on the
previously submitted `d85b5061d2e6aa12fd0d7bcedf7b493a695c40c0`.
See [PROTOCOL_IMPLEMENTATION.md](PROTOCOL_IMPLEMENTATION.md) for behavior,
reproduction commands, and remaining boundaries.

The 2026-11-09 handoff documents and validation reports describe their frozen
historical versions. Their hashes and performance results do not describe this
protocol revision, and their "protocol unpublished" notes are historical.

This branch implements a standalone, single-process database for the
`2026-competition-round2` challenge. It does not use seekdb, SQLite, RocksDB,
Faiss, VSAG, or another database/index engine to execute operations.

The default interface emits ready after recovery and accepts JSONL
execute/shutdown requests. The raw-SQL adapter remains explicitly opt-in with
`--dev-protocol`. Public checks and local regressions do not prove that all
formal cases or ranking requirements pass.

## Build and run locally

Linux x86_64, C++17, POSIX file APIs, CMake 3.16+ and Python 3 for tests:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 tests/acceptance.py --binary ./build/minivectordb
./build/minivectordb --data-dir ./build/demo-data --dev-protocol
```

The explicitly selected development adapter accepts one complete SQL statement per input line, emits one
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

Restart with the same `--data-dir` to query committed records. Docker defaults
to the official JSONL interface (not the raw SQL example above):

```sh
docker build -t minivectordb:jsonl .
docker run --rm -i --read-only --network=none -v minivectordb-data:/data minivectordb:jsonl
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
  exact scan. Each request's exact/ann mode is validated and passed to the
  engine; ann currently uses an explicit exact-scan fallback. An accelerated
  approximate index is unfinished, and hidden-test acceptance of the fallback
  has not been established.
* Large results use external sorting and streaming. Relevant 128 MiB cgroup
  regressions passed; these do not prove unlimited capacity or memory headroom.
* The journal supports checkpoint/compaction with crash-boundary tests. The V2
  key index uses a compact shared arena, but still consumes O(N) resident memory.
  Two million short records completed the tested stages under 128 MiB; larger
  capacity and other distributions remain unverified. UPDATE latency regression
  is the next investigation, not a claim of universal performance improvement.
* Unsupported SQL must error. NULL, joins, aggregates, expressions in assignments,
  nested transactions and primary-key updates are outside this implementation.

The published protocol checker and its unchanged config must be used against
the actual Docker default entrypoint. No formal submission, ranking, full-score
outcome, or measured performance improvement is claimed for this revision.
