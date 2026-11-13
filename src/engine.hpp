#pragma once
#include "storage.hpp"
#include <memory>
#include <ostream>
#include <variant>
#include <vector>

namespace mvdb {
class RowStream;
using Cell = std::variant<int64_t, std::string, std::vector<float>, double>;
enum class SearchMode { Exact, Ann };
struct Result {
  std::vector<std::string> columns;
  std::vector<std::vector<Cell>> rows;
  uint64_t affected = 0;
  std::shared_ptr<RowStream> stream;
  bool reports_affected = false;
};
class Engine {
public:
  explicit Engine(const std::string &directory);
  ~Engine();
  Result execute(const std::string &sql, SearchMode mode = SearchMode::Exact);
  void prepare_shutdown();

private:
  Store store_;
  std::string directory_;
  struct Cache;
  std::unique_ptr<Cache> cache_;
  Result execute_statement(const Statement &statement);
  // Optimistic direct path for multi-row INSERT ... VALUES; returns false when
  // the statement is outside the fast-path grammar so the parser can handle it.
  bool try_fast_insert(const std::string &sql, Result &result);
  Result execute_ann(const Statement &statement);
};
std::string result_json(const Result &result);
void write_result_json(std::ostream &out, const Result &result);
// id_json is the validated, unconverted JSON token from parse_request.
void write_protocol_result_json(std::ostream &out, const Result &result,
                                const std::string &id_json);
std::string protocol_error_json(const std::string &id_json,
                                const std::string &code,
                                const std::string &message);
std::string error_json(const std::string &code, const std::string &message);
} // namespace mvdb
