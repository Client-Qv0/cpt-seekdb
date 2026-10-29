# Snapshot pipeline optimization (2026-10-30)

Parent: `d44c64858d3ced8ba8597bc78b139c083ba9a22c`.
User-reported platform result for this parent: build=2.009x,
query=1.545x, gates=pass. The earlier CPU/GPU comparison report uses a different
measurement method and must not be used to predict the contest score.

The optimization targets are build 3.5–4x and query >=1.7x against the frozen
V5 GPU baseline. These are goals, **not measured results for this change**.

## Implementation

- Deserializing a CAGRA snapshot restores its GPU graph/dataset without also
  allocating, zeroing and downloading the full FP32 host dataset. Host vectors
  are restored on demand before updates/rebuilds or filtered CPU fallback;
  queries continue to run the supplied hipVS CAGRA search. A failed download
  does not publish a partially restored host buffer and is propagated to callers.
- Snapshot payloads use shared temporary-file mappings to eliminate the extra
  16 MiB userspace copy buffers on both serialization and deserialization.
  If mapping is unavailable, the existing buffered file I/O remains available.
- Snapshot format, FP32 data, row IDs, graph degree, intermediate degree,
  NN-Descent iterations and all query search parameters are unchanged.
- There is no cross-round graph cache, evaluation-phase detection, prebuilt
  graph, or deferred GPU construction. The first query still needs the complete
  built/restored GPU index. Only an unused *host duplicate* is deferred.

For 250,000 rows this removes an eager 122 MiB (128 dimensions) / 244 MiB
(256 dimensions) host allocation and corresponding device-to-host transfer
per loaded snapshot. This byte count is not a claimed time speedup.

## Local verification

The CPU-only test exercises deferred host restoration, no redundant second
download, append-after-restoration, failed-copy rollback and retry, invalid
shapes/overflow, a 17 MiB+123-byte mapped round trip and visibility to a separate
file descriptor while the mapping remains live. Invalid mappings are rejected.

```bash
g++ -std=c++17 -O2 -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-omit-frame-pointer \
  tools/hipvs_bridge/test_snapshot_io.cpp -o /tmp/test_snapshot_io
/tmp/test_snapshot_io
```

Result: PASS under ASan/UBSan. The complete modified `ob_vsag_adaptor.cpp`
also passed syntax checking and object compilation with the available seekdb
dependency toolchain, both with GPU declarations disabled and with
`OB_BUILD_CUVS`/`OB_BUILD_CUVS_TRACE` enabled. This is not a full seekdb link,
ROCm bridge build, or GPU SQL integration test.

## Remaining verification

No accessible AMD server was available. GPU Recall, end-to-end build time,
4096-query Top-10/Top-100 QPS, GPU profiler checks and peak VRAM have **not**
been measured for this revision. There is no local claim that the goals or
all official gates are met. The user authorized one platform evaluation after
the available local checks, without requiring a separate GPU server retest.
