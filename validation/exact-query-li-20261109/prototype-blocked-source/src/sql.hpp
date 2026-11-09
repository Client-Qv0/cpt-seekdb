#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace mvdb {
struct Error : std::runtime_error {
  std::string code;
  Error(std::string c, std::string m) : std::runtime_error(std::move(m)), code(std::move(c)) {}
};
enum class Type { BigInt, Varchar, Vector };
struct Column { std::string name; Type type; uint32_t size = 0; bool primary = false; };
// Literals preserve text until schema-directed conversion. Numbers must not pass through double for BIGINT.
struct Literal { std::string text; bool quoted = false; };
struct Expr { enum Kind { ColumnRef, Distance, Star } kind = ColumnRef; std::string column; Literal vector; std::string alias; };
struct Condition { std::string column; std::string op; Literal value; };
struct Order { std::string name; bool descending = false; };
struct Statement {
  enum Kind { CreateTable, CreateIndex, Insert, Select, Update, Delete, Begin, Commit, Rollback } kind;
  std::string table, index_name, index_column;
  std::vector<Column> schema;
  std::vector<std::string> insert_columns;
  std::vector<std::vector<Literal>> values;
  std::vector<Expr> projections;
  std::vector<Condition> conditions;
  std::vector<Order> order;
  std::optional<uint64_t> limit;
  std::vector<std::pair<std::string, Literal>> assignments;
};
Statement parse_sql(const std::string& sql);
}
