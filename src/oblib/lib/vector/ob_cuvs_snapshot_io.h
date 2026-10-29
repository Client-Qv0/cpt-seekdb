/* Copyright (c) 2025 OceanBase. Licensed under the Apache License, Version 2.0. */
#ifndef OCEANBASE_LIB_VECTOR_OB_CUVS_SNAPSHOT_IO_H_
#define OCEANBASE_LIB_VECTOR_OB_CUVS_SNAPSHOT_IO_H_

#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstdint>
#include <limits>
#include <new>
#include <vector>

namespace oceanbase {
namespace common {
namespace obvsag {

// Owns only a temporary file mapping, never the descriptor or a GPU graph.
// MAP_SHARED makes completed input writes visible to hipVS's separate file
// descriptor without copying the snapshot through another userspace buffer.
class CuvsSnapshotMapping {
public:
  CuvsSnapshotMapping() : data_(MAP_FAILED), size_(0) {}
  ~CuvsSnapshotMapping() { if (data_ != MAP_FAILED) { ::munmap(data_, size_); } }
  bool open(int fd, uint64_t bytes, bool writable)
  {
    if (data_ != MAP_FAILED || bytes == 0 ||
        bytes > std::numeric_limits<size_t>::max() ||
        bytes > static_cast<uint64_t>(std::numeric_limits<off_t>::max())) { return false; }
    struct stat st;
    if (::fstat(fd, &st) != 0 || st.st_size < 0) { return false; }
    if (writable) {
      if (::ftruncate(fd, static_cast<off_t>(bytes)) != 0) { return false; }
    } else if (static_cast<uint64_t>(st.st_size) < bytes) { return false; }
    data_ = ::mmap(nullptr, static_cast<size_t>(bytes),
                   writable ? (PROT_READ | PROT_WRITE) : PROT_READ, MAP_SHARED, fd, 0);
    if (data_ == MAP_FAILED) { return false; }
    size_ = static_cast<size_t>(bytes);
    return true;
  }
  char *data() { return static_cast<char *>(data_); }
private:
  CuvsSnapshotMapping(const CuvsSnapshotMapping &) = delete;
  CuvsSnapshotMapping &operator=(const CuvsSnapshotMapping &) = delete;
  void *data_;
  size_t size_;
};

// A loaded CAGRA snapshot already owns the full FP32 dataset on the device.
// Materialize a host copy only for an update/rebuild or a filtered CPU fallback.
// Publish atomically: a failed copy must not leave a partial buffer that a later
// caller could mistake for a valid dataset. Caller holds the registry mutex.
inline bool cuvs_materialize_host_vectors(std::vector<float> &vectors, size_t rows,
    int dim, void *bridge, int (*copy)(void *, float *, long, long))
{
  if (dim <= 0 || rows > static_cast<size_t>(std::numeric_limits<long>::max()) ||
      rows > std::numeric_limits<size_t>::max() / sizeof(float) / static_cast<size_t>(dim)) {
    return false;
  }
  const size_t count = rows * static_cast<size_t>(dim);
  if (vectors.size() == count) { return true; }
  if (!vectors.empty() || bridge == nullptr || copy == nullptr) { return false; }
  try {
    std::vector<float> restored(count);
    if (copy(bridge, restored.data(), static_cast<long>(rows), dim) != 0) { return false; }
    vectors.swap(restored);
  } catch (const std::bad_alloc &) { return false; }
  return true;
}

} // namespace obvsag
} // namespace common
} // namespace oceanbase
#endif
