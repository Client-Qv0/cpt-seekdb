/* CPU-only tests for snapshot I/O and deferred host copies; no hipVS stubs. */
#include "../../src/oblib/lib/vector/ob_cuvs_snapshot_io.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <sstream>
#include <string>

using namespace oceanbase::common::obvsag;

struct DeviceDataset {
  std::vector<float> values;
  int calls = 0;
  bool fail = false;
};
static int copy_dataset(void *ptr, float *out, long rows, long dim)
{
  DeviceDataset &src = *static_cast<DeviceDataset *>(ptr);
  ++src.calls;
  assert(src.values.size() == static_cast<size_t>(rows * dim));
  std::memcpy(out, src.values.data(), src.values.size() * sizeof(float));
  return src.fail ? 1 : 0;
}

int main()
{
  DeviceDataset device;
  device.values = {1, 2, 3, 4, 5, 6};
  std::vector<float> host;
  // A snapshot query needs no host copy; an actual update materializes once.
  assert(device.calls == 0 && host.empty());
  assert(cuvs_materialize_host_vectors(host, 3, 2, &device, copy_dataset));
  assert(host == device.values && device.calls == 1);
  assert(cuvs_materialize_host_vectors(host, 3, 2, &device, copy_dataset));
  assert(device.calls == 1);
  host.insert(host.end(), {7, 8});
  assert(cuvs_materialize_host_vectors(host, 4, 2, &device, copy_dataset));
  assert(host[0] == 1 && host[7] == 8 && device.calls == 1);
  // Failed transfer is not published, and the next operation can retry.
  host.clear(); device.fail = true;
  assert(!cuvs_materialize_host_vectors(host, 3, 2, &device, copy_dataset));
  assert(host.empty());
  device.fail = false;
  assert(cuvs_materialize_host_vectors(host, 3, 2, &device, copy_dataset));
  assert(host == device.values && device.calls == 3);
  assert(!cuvs_materialize_host_vectors(host, 4, 2, &device, copy_dataset));
  assert(!cuvs_materialize_host_vectors(host, 3, 0, &device, copy_dataset));
  assert(!cuvs_materialize_host_vectors(host, SIZE_MAX, 2, &device, copy_dataset));
  host.clear();
  assert(!cuvs_materialize_host_vectors(host, 3, 2, nullptr, copy_dataset));

  FILE *file = ::tmpfile(); assert(file);
  const size_t bytes = 17 * 1024 * 1024 + 123; // past the old 16 MiB boundary
  std::string payload(bytes, '\0');
  for (size_t i = 0; i < bytes; ++i) { payload[i] = static_cast<char>(i * 31 + i / 257); }
  {
    CuvsSnapshotMapping writable;
    assert(writable.open(::fileno(file), bytes, true));
    std::istringstream input(payload);
    input.read(writable.data(), bytes);
    assert(input.gcount() == static_cast<std::streamsize>(bytes));
    // hipVS opens a separate descriptor via /proc/self/fd; verify visibility
    // while mapping is alive, without msync/fsync or an extra buffered copy.
    char path[64]; std::snprintf(path, sizeof(path), "/proc/self/fd/%d", ::fileno(file));
    FILE *reader = ::fopen(path, "rb"); assert(reader);
    std::string readback(bytes, '\0');
    assert(::fread(&readback[0], 1, bytes, reader) == bytes);
    assert(readback == payload);
    ::fclose(reader);
  }
  {
    CuvsSnapshotMapping readable;
    assert(readable.open(::fileno(file), bytes, false));
    std::ostringstream output;
    output.write(readable.data(), bytes);
    assert(output.str() == payload);
    assert(!readable.open(::fileno(file), bytes, false));
  }
  CuvsSnapshotMapping invalid;
  assert(!invalid.open(-1, bytes, false));
  assert(!invalid.open(::fileno(file), 0, false));
  assert(!invalid.open(::fileno(file), UINT64_MAX, true));
  assert(!invalid.open(::fileno(file), bytes + 1, false));
  ::fclose(file);
  std::cout << "PASS: deferred copy/retry/update, mapped cross-descriptor round-trip, invalid sizes\n";
}
