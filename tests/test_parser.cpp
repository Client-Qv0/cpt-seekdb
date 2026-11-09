#include "sql.hpp"
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0;
void check(bool condition) {
  ++checks;
  if (!condition) throw std::runtime_error("Parser assertion failed at check " + std::to_string(checks));
}
void reject(const std::string& sql) {
  try { mvdb::parse_sql(sql); }
  catch (const mvdb::Error& e) { check(e.code == "SYNTAX"); return; }
  throw std::runtime_error("Unexpectedly accepted: " + sql);
}
}

int main() {
  using namespace mvdb;
  auto s = parse_sql("CrEaTe TABLE `Docs` (ID BIGINT PRIMARY KEY, category VARCHAR(32), embedding VECTOR(4)); -- end\n");
  check(s.kind == Statement::CreateTable && s.table == "docs");
  check(s.schema.size() == 3 && s.schema[0].primary && s.schema[0].name == "id");
  check(s.schema[1].type == Type::Varchar && s.schema[1].size == 32);
  check(s.schema[2].type == Type::Vector && s.schema[2].size == 4);
  s = parse_sql("CREATE TABLE t (id BIGINT, s VARCHAR(3), PRIMARY KEY (id))");
  check(s.schema[0].primary && !s.schema[1].primary);
  s = parse_sql("CREATE VECTOR INDEX idx ON docs(embedding)");
  check(s.kind == Statement::CreateIndex && s.index_name == "idx" && s.index_column == "embedding");
  s = parse_sql("INSERT INTO docs (id, category, embedding) VALUES (-9223372036854775808, '中文🙂', '[1, 2, 3, 4]'), (9223372036854775807, 'O''Brien', '[0,0,0,0]');");
  check(s.values.size() == 2 && s.insert_columns.size() == 3);
  check(s.values[0][0].text == "-9223372036854775808" && !s.values[0][0].quoted);
  check(s.values[1][0].text == "9223372036854775807");
  check(s.values[0][1].text == "中文🙂" && s.values[1][1].text == "O'Brien");
  s = parse_sql("INSERT INTO t VALUES (1, 'x; DELETE FROM t;', '\\n\\t\\\\\\\'')");
  check(s.values[0][1].text == "x; DELETE FROM t;");
  check(s.values[0][2].text == "\n\t\\'");
  s = parse_sql("SELECT id, L2_DISTANCE(embedding, '[.9,.1,0,0]') AS distance FROM docs WHERE category='database' AND (id >= -5 AND id < 20) ORDER BY distance ASC, id DESC LIMIT 2");
  check(s.projections.size() == 2 && s.projections[1].kind == Expr::Distance);
  check(s.projections[1].alias == "distance" && s.projections[1].vector.quoted);
  check(s.conditions.size() == 3 && s.conditions[1].op == ">=");
  check(s.order.size() == 2 && !s.order[0].descending && s.order[1].descending && s.limit == 2);
  s = parse_sql("SELECT * FROM t LIMIT 18446744073709551615");
  check(s.limit == UINT64_MAX && s.projections[0].kind == Expr::Star);
  s = parse_sql("SELECT * FROM t LIMIT 0"); check(s.limit == 0);
  s = parse_sql("/* leading */ UPDATE t SET s='/* text */', v='[1e2, -2.5]' WHERE id=+1 # trailing\n");
  check(s.kind == Statement::Update && s.assignments.size() == 2 && s.conditions[0].value.text == "+1");
  s = parse_sql("SELECT * FROM t; -- comment\n");
  check(s.kind == Statement::Select);
  s = parse_sql("SELECT * FROM t; --\tcomment");
  check(s.kind == Statement::Select);
  s = parse_sql("DELETE FROM t WHERE id <= 3"); check(s.kind == Statement::Delete);
  check(parse_sql("BEGIN;").kind == Statement::Begin);
  check(parse_sql("COMMIT").kind == Statement::Commit);
  check(parse_sql("ROLLBACK").kind == Statement::Rollback);
  s = parse_sql("SELECT `select` AS `order` FROM `table`");
  check(s.projections[0].column == "select" && s.projections[0].alias == "order");
  s = parse_sql("INSERT INTO t VALUES (1, 1.25e-4, .5, -0.1, 1.)");
  check(s.values[0][1].text == "1.25e-4" && s.values[0][2].text == ".5");
  for (const auto& sql : {
    "", ";", "SELECT", "SELECT * FROM t; DELETE FROM t", "SELECT * FROM t;;",
    "INSERT INTO t VALUES (NULL)", "INSERT INTO t VALUES (NaN)", "INSERT INTO t VALUES (Infinity)",
    "INSERT INTO t VALUES (1e)", "INSERT INTO t VALUES (1e+)", "INSERT INTO t VALUES (1abc)",
    "INSERT INTO t VALUES (1.2.3)", "INSERT INTO t VALUES (1 + 2)", "INSERT INTO t VALUES ('unterminated)",
    "INSERT INTO t VALUES ()", "SELECT * FROM t WHERE id != 1", "SELECT * FROM t WHERE id <> 1",
    "SELECT * FROM t WHERE id=1 OR id=2", "SELECT * FROM t WHERE id IN (1)",
    "SELECT * FROM t JOIN x ON t.id=x.id", "SELECT COUNT(*) FROM t", "SELECT DISTINCT id FROM t",
    "SELECT * FROM t LIMIT -1", "SELECT * FROM t LIMIT 1.0", "SELECT * FROM t LIMIT 18446744073709551616",
    "SELECT * FROM t LIMIT 1 OFFSET 1", "CREATE TABLE t (id BIGINT PRIMARY KEY, v VECTOR(0))",
    "CREATE TABLE t (id BIGINT PRIMARY KEY, v VECTOR(4294967296))", "CREATE TABLE t ()",
    "CREATE TABLE t (id BIGINT PRIMARY KEY, PRIMARY KEY (id))", "CREATE TABLE t (id BIGINT, PRIMARY KEY (missing))",
    "CREATE TABLE t (id BIGINT, PRIMARY KEY (id), PRIMARY KEY (id))", "SELECT * AS x FROM t",
    "DELETE FROM t WHERE id=1--2", "UPDATE t SET n=9 WHERE id=1--2",
    "SELECT * FROM t--not_a_comment", "SELECT * FROM t; --",
    "SELECT * FROM t; -- comment\r DELETE FROM t", "SELECT * FROM t; # comment\r DELETE FROM t",
    "SELECT * FROM t /*", "SELECT * FROM t /* never closed", "/*! SELECT * FROM t */",
    "SELECT /*+ index(t) */ * FROM t", "BEGIN TRANSACTION", "ALTER TABLE t ADD COLUMN x BIGINT",
    "SELECT null FROM t", "SELECT * FROM t WHERE id=", "UPDATE t SET id=id+1", "SELECT * FROM ``"
  }) reject(sql);
  std::cout << "parser checks passed: " << checks << '\n';
}
