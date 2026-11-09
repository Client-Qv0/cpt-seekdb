#pragma once
#include "storage.hpp"
#include <memory>
#include <ostream>
#include <variant>
#include <vector>

namespace mvdb {
class RowStream;
using Cell = std::variant<int64_t, std::string, std::vector<float>, double>;
struct Result {
  std::vector<std::string> columns;
  std::vector<std::vector<Cell>> rows;
  uint64_t affected = 0;
  std::shared_ptr<RowStream> stream;
};
class Engine {
public:
  explicit Engine(const std::string &directory);
  ~Engine();
  Result execute(const std::string &sql);

private:
  Store store_;
  std::string directory_;
  struct Cache;
  std::unique_ptr<Cache> cache_;
  Result execute_statement(const Statement &statement);
};
std::string result_json(const Result &result);
void write_result_json(std::ostream &out, const Result &result);
std::string error_json(const std::string &code, const std::string &message);
} // namespace mvdb
