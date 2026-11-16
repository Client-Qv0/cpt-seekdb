#pragma once
#include "sql.hpp"
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

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

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} // namespace mvdb
