#pragma once
#include "sql.hpp"
#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace mvdb {
// Values stay on disk; the implementation may keep keys and file offsets in
// memory. A statement is atomic independently of its enclosing explicit
// transaction.
class Store {
public:
  explicit Store(const std::string &directory);
  ~Store();
  Store(const Store &) = delete;
  Store &operator=(const Store &) = delete;
  bool in_transaction() const;
  // Preserve the storage health check when serving cached metadata.
  void check_available() const;
  void begin();
  void commit();
  void rollback();
  // Explicit, checked shutdown. Unlike the destructor, failures are reported.
  void close();
  // Compacts only committed data; rejects an active statement or transaction.
  void checkpoint();
  void begin_statement();
  void finish_statement();
  void abort_statement();
  std::optional<std::string> metadata(const std::string &table) const;
  void set_metadata(const std::string &table, const std::string &data);
  std::optional<std::string> get(const std::string &table, int64_t key) const;
  void put(const std::string &table, int64_t key, const std::string &data);
  void erase(const std::string &table, int64_t key);
  // Emits visible rows in ascending primary-key order. Callback may stage
  // writes.
  void scan(const std::string &table,
            const std::function<void(int64_t, const std::string &)> &fn) const;

  struct KeyRange {
    int64_t first = std::numeric_limits<int64_t>::min();
    int64_t last = std::numeric_limits<int64_t>::max();
  };
  // Visits visible rows within a closed primary-key interval. A false return
  // from the callback stops the scan, after consuming that row.
  void scan_until(const std::string &table, KeyRange range, bool descending,
      const std::function<bool(int64_t, const std::string &)> &fn) const;

  class ReadMapping {
  public:
    const std::shared_ptr<const char> &data() const { return data_; }

  private:
    friend class Store;
    std::shared_ptr<const char> data_;
    uint64_t size_ = 0;
    uint64_t device_ = 0;
    uint64_t inode_ = 0;
  };
  // Engine discards this immutable view before starting any mutation or
  // transaction that could rewrite or truncate the journal.
  ReadMapping map_committed() const;
  // Visits committed rows in key order. Each bounded view is valid during
  // its callback. The offset is measured from the start of the mapping.
  void scan_mapped(const std::string &table, const ReadMapping &mapping,
      const std::function<void(int64_t, std::string_view, uint64_t)> &fn) const;
  void scan_with_offsets(const std::string &table,
      const std::function<void(int64_t, const std::string &, uint64_t)> &fn) const;
private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} // namespace mvdb
