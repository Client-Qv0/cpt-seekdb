#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

namespace mvdb {
class RowStream {
 public:
  virtual ~RowStream() = default;
  virtual void reset() = 0;
  virtual bool next(std::string& json_row) = 0;
};

// The budget bounds buffered records, not the size of the caller's current row.
// One oversized input/output row is allowed. Merge memory and open fd counts
// stay bounded independently of the number of runs, rows, or payload lengths.
class SpillSorter {
 public:
  explicit SpillSorter(const std::string& data_dir, size_t memory_budget = 4 * 1024 * 1024);
  ~SpillSorter();
  SpillSorter(const SpillSorter&) = delete;
  SpillSorter& operator=(const SpillSorter&) = delete;
  void add(std::string binary_sort_key, std::string json_row);
  std::shared_ptr<RowStream> finish(std::optional<uint64_t> limit = std::nullopt);
 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
}
