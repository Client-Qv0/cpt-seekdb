# hipVS/cuVS GPU vector backend

Status: **Offline DDL builds and persists GPU CAGRA graphs** behind seekdb's
HNSW/HGRAPH SQL interface. Validation targets AMD `gfx1100` with ROCm 7.2.4.
This is a CAGRA backend, not an export to the original VSAG HNSW graph format.

## Scope

The backend adds optional hipVS/cuVS acceleration behind seekdb's existing
vector adaptor. It does not replace VSAG globally.

- GPU support is compiled only with `OB_BUILD_CUVS=ON`; the default is `OFF`.
- A dense L2 HNSW/HGRAPH index opts in with `WITH (lib=cuvs)`.
- `lib=vsag` indexes keep their existing CPU behavior.
- Cosine and inner-product metrics are rejected for `lib=cuvs` at DDL time.
- Queries that cannot use the GPU result (filters, deletes, stale indexes)
  build a VSAG fallback lazily. GPU snapshot construction/loading still requires
  a working GPU; query fallback is not a guarantee of GPU-free snapshot recovery.
- `dbms_vector.batch_knn` exposes one-call batched GPU ANN for explicit batch
  workloads.

The product integration lives in:

- [`ob_vsag_adaptor.cpp`](../../src/oblib/lib/vector/ob_vsag_adaptor.cpp):
  per-index marking, buffered vectors, offline/lazy CAGRA construction,
  persisted GPU snapshots, freshness fallback, trace points, and batch entry points.
- [`ob_plugin_vector_index_adaptor.cpp`](../../src/observer/vector_index/ob_plugin_vector_index_adaptor.cpp):
  maps declarative `lib=cuvs` indexes to the adaptor handle.
- [`ob_vector_index_util.cpp`](../../src/observer/vector_index/ob_vector_index_util.cpp):
  validates the L2-only DDL contract.
- [`ob_dbms_vector_mysql.cpp`](../../src/pl/sys_package/ob_dbms_vector_mysql.cpp):
  implements `dbms_vector.batch_knn`.

## Bridge

seekdb links a small C ABI bridge instead of importing hipVS/cuVS C++ types into
the server. The maintained bridge source and build entry point are under
[`tools/hipvs_bridge`](../../tools/hipvs_bridge/):

```bash
tools/hipvs_bridge/build.sh /work/bridge/libseekdb_cuvs_bridge.so
```

The bridge exports:

```text
seekdb_cuvs_build
seekdb_cuvs_search
seekdb_cuvs_free
seekdb_cuvs_cagra_knn
seekdb_cuvs_serialize
seekdb_cuvs_deserialize
seekdb_cuvs_get_dataset
```

Build seekdb with the resulting library:

```bash
./build.sh release \
  -DOB_BUILD_CUVS=ON \
  -DOB_BUILD_CUVS_TRACE=OFF \
  -DCUVS_BRIDGE_LIB=/work/bridge/libseekdb_cuvs_bridge.so \
  --make -j64
```

For a CPU-only build, leave the defaults or pass:

```bash
./build.sh release \
  -DOB_BUILD_CUVS=OFF \
  -DOB_BUILD_CUVS_TRACE=OFF \
  --make -j64
```

## SQL usage

Per-index GPU opt-in:

```sql
CREATE TABLE items(
  id BIGINT PRIMARY KEY,
  embedding VECTOR(128),
  VECTOR INDEX idx_embedding(embedding)
    WITH (distance=l2, type=hnsw, lib=cuvs)
);
```

Explicit batch ANN writes results to a caller-created output table:

```sql
CALL dbms_vector.batch_knn(
  "items",
  "query_vectors",
  10,
  "batch_results"
);
```

See [`examples/batch_knn.sql`](examples/batch_knn.sql) for the table contract.

## Validation

The self-contained GPU smoke runner generates deterministic vectors and ground
truth; it does not use private `/work/datasets` or `/work/bench` assets:

```bash
LD_LIBRARY_PATH=/work/bridge:/opt/hipvs/lib:/opt/rocm/lib \
  docs/gpu-vector-index-hipvs-cuvs/validation/run_gpu_smoke.sh \
    --observer /path/to/trace-build/seekdb \
    --bridge /work/bridge/libseekdb_cuvs_bridge.so \
    --base-dir /tmp/seekdb-cuvs-smoke \
    --port 2981 \
    --render /dev/dri/renderD135 \
    --evidence /tmp/seekdb-cuvs-evidence
```

The runner validates:

- cuVS L2 build/serve and same-process VSAG isolation;
- non-L2 DDL rejection;
- filter, delete, and freshness fallback;
- threshold-triggered CAGRA rebuild;
- one-call `batch_knn`, row cardinality, and recall for Top-10 and Top-100;
- GPU device file descriptors and hidden-GPU fallback;
- bounded observer cleanup and closed ports.

The runner writes a machine-readable `summary.json` into its evidence directory.
The dated [AMD validation report](validation/AMD_VALIDATION_2026-10-29.md)
records the CPU comparison, regression results, and limitations of the measured
candidate, with raw evidence linked for reproduction.
The no-GPU DDL contract remains covered by
[`vector_index_cuvs_ddl.test`](../../tools/deploy/mysql_test/test_suite/vector_index/t/vector_index_cuvs_ddl.test).

## Offline build benchmark

[`validation/benchmark_offline_ddl.py`](validation/benchmark_offline_ddl.py)
compares real `CREATE VECTOR INDEX` calls with `lib=vsag` and `lib=cuvs` in
the same server. It uses independent queries, exact float64 L2 ground truth,
and verifies sample ground truth against SQL exact search before index creation.
It sets and reads back the session `ob_hnsw_ef_search`; the DDL option alone
does not override the query session default. Import, DDL, first query, and
steady query latencies are recorded separately, with per-query neighbors and
recall. Repeated runs alternate backend order and save binary/data checksums.

Install NumPy and PyMySQL, start the GPU-enabled server, then run:

```bash
OPENBLAS_NUM_THREADS=1 python3 validation/benchmark_offline_ddl.py \
  --data-dir /path/to/data/n1m_d128 \
  --output /path/to/evidence/n1m_d128.json \
  --database amd_bench_unique_run_name \
  --rows 1000000 --dim 128 --queries 200 --repeats 3 --ef-search 1000 \
  --label candidate \
  --observer-bin /path/to/seekdb \
  --bridge-lib /path/to/libseekdb_cuvs_bridge.so
```

Run from this documentation directory. The database name must be unused and
begin with `amd_bench_`. Only tables created by the run are dropped. Use a
different data directory for different dimensions or row counts. CPU settings
are `m=16, ef_construction=200`; GPU construction uses NN-Descent with graph
degree 128, intermediate degree 128, and 65 iterations. These are different
algorithms, so compare build time **together with measured recall**, not by
assuming identical SQL parameters mean identical work.

The bridge explicitly selects CAGRA `AUTO` search with at least 1024 candidates.
The shipped hipVS C API otherwise defaults to `SINGLE_CTA`, which rejects more
than 512 candidates. The extended bridge persistence test exercises single and
batched Top-10/Top-200 queries before and after reload.

Run that regression against the same bridge used by the server:

```bash
# From the repository root; adjust the installation paths if necessary.
BRIDGE_DIR=/path/to/bridge
g++ -O2 -std=c++17 tools/hipvs_bridge/test_persistence.cpp \
  -Itools/hipvs_bridge -L"$BRIDGE_DIR" -lseekdb_cuvs_bridge \
  -Wl,-rpath,"$BRIDGE_DIR" -Wl,-rpath-link,/opt/hipvs/lib \
  -Wl,-rpath-link,/opt/rocm/lib -o /tmp/test_cuvs_persistence
export LD_LIBRARY_PATH="$BRIDGE_DIR:/opt/hipvs/lib:/opt/rocm/lib"
/tmp/test_cuvs_persistence write /tmp/cuvs-regression.bin
/tmp/test_cuvs_persistence read /tmp/cuvs-regression.bin
```

The read test intentionally attempts two wrong snapshot shapes before the valid
load; their mismatch diagnostics are expected. Both commands must exit zero.

For an isolated SQL lifecycle test without Docker, use a TRACE-enabled observer
and an unused port/run directory:

```bash
python3 docs/gpu-vector-index-hipvs-cuvs/validation/run_sql_lifecycle.py \
  --observer /path/to/trace-build/seekdb --bridge-dir /path/to/bridge \
  --data-dir /path/to/data/n100k_d128 \
  --run-dir /path/to/new-lifecycle-run --port 2991
```

It checks offline DDL, GPU query after restart without rebuilding, CPU-index
isolation, filters, deletes, and new inserts, then stops only its own observer.
Its `summary.json`, SQL runtime directory, and trace remain in the run directory.

## Current limitations

- Phase 1 supports dense float32 L2 indexes only.
- Offline DDL persists the CAGRA graph and its dataset. Incremental buffers
  can trigger lazy rebuilds; GPU-free loading of GPU snapshots is not supported.
- The explicit batch API rebuilds its CAGRA index per call.
- GPU validation is manual because upstream CI has no compatible GPU runner.
- Multi-GPU and long-duration coverage remain outside the current validation.
