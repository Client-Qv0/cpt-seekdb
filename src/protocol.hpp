#pragma once
#include "engine.hpp"
#include <string>

namespace mvdb {
struct Request {
  enum class Op { Execute, Shutdown };
  // Validated JSON token, not a floating-point conversion of a request number.
  std::string id_json = "null";
  Op op = Op::Execute;
  std::string sql;
  SearchMode search_mode = SearchMode::Exact;
};
// Parses the whole JSON object before execution. Invalid requests are local
// protocol errors; the official protocol only specifies well-formed requests.
void parse_request(const std::string &line, Request &request);
} // namespace mvdb

