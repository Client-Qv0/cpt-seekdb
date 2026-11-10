# Published JSONL adapter

The protocol source is [STDIO_PROTOCOL.md at f4d4e266](https://github.com/oceanbase/seekdb/blob/f4d4e26653af823a7601668802f80e374ad6643c/STDIO_PROTOCOL.md).
The former submitted version is d85b5061d2e6aa12fd0d7bcedf7b493a695c40c0.
This change does not alter the journal format, SQL grammar, commit marker
durability, query ordering, or the vector distance calculation.

## Entry and behavior

- The native program and default Docker command open /data, recover, then emit
  exactly {"type":"ready"} followed by newline and flush.
- Each complete JSON object is parsed before any SQL executes. The original
  validated JSON token for id is returned without number conversion, preserving
  integer/decimal/string/other JSON types and large integer precision.
- execute dispatches the SQL string and validated per-request search_mode.
  Queries return columns/rows, writes return integer affected_rows, and
  DDL/transaction controls return id/ok. SQL errors return a nested error
  object and leave the process available for the next request.
- Rows retain the existing bounded streaming/external-sort implementation.
  Failure while emitting a response terminates with stderr diagnostics; a
  second JSON error object is never appended to a partial response.
- shutdown rolls back any active transaction, syncs the journal (including
  rollback truncation), checks descriptor closes, destroys the engine, then
  acknowledges and exits 0. Failure during close is reported as an error and a
  nonzero exit, never a successful shutdown acknowledgement.
- EOF also cleans up without an unsolicited response. No network server is
  started. All persistent and spill files remain under the data directory.
- --dev-protocol explicitly selects the historical raw-SQL diagnostic interface.
  It is never required by the official checker.

## Reproduction

Use Linux x86_64, C++17, CMake and Docker. Build from source:

    docker build --no-cache -t minivectordb:jsonl .

Obtain the official repository in a separate directory and check out the exact
official commit above. From that checkout, with its original files/config:

    python3 protocol_check/run.py --image minivectordb:jsonl --handshake-only --output /path/to/new-handshake-results
    python3 protocol_check/run.py --image minivectordb:jsonl --case sql_crud --output /path/to/new-crud-results
    python3 protocol_check/run.py --image minivectordb:jsonl --output /path/to/new-public-results

Each output path must be new. The checker defaults include read-only root,
writable /data, no network, 2 CPUs, 2 GiB memory with no swap, and 128 PIDs.
Do not change the checker or relax its configuration to accommodate this program.

Additional native regression:

    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build --parallel 2
    ctest --test-dir build --output-on-failure

The protocol unit test covers lossless request IDs, JSON grammar, escaped
Unicode/surrogate pairs, UTF-8 validation, official output fields, and checked
shutdown rollback/reopening. Existing tests using --dev-protocol remain
development tests; they are not substitutes for official JSONL checks.

## Explicit limits and unresolved contracts

- ann is recognized and dispatched in the database, not swallowed by a bridge.
  It currently uses a named exact-scan fallback and returns exact TopK results.
  CREATE VECTOR INDEX still records metadata without an approximate index.
  This is not a claim of ANN implementation or hidden-test acceptance.
- SQL NULL is not added by this protocol patch. The existing SQL subset rejects
  it. The protocol's representation rule for NULL does not specify additional
  SQL grammar. Formal NULL requirements remain to be confirmed.
- The published error_codes map is empty. Existing nonempty database codes are
  retained; no hidden code mapping is guessed.
- Malformed JSON, duplicate keys, invalid UTF-8/surrogates, missing required
  fields and unsupported operations/modes are local error policies. If no
  syntactically valid complete request ID is available, the error uses null.
  Valid request semantic errors retain their ID. Valid requests without
  search_mode default to exact, matching the published skeleton.
- Arbitrary valid ID JSON values are preserved. The official public driver
  ordinarily generates integer IDs; wider ID tests are supplemental.
- Nested JSON values have a defensive depth limit of 128, not an asserted
  official requirement. The published 16 MiB limit applies to responses,
  not a newly invented SQL request limit.
- Hidden cases, official platform image/command identity, ranking, and ANN
  workload performance have not been established by passing local public cases.

