// The optimistic INSERT path must agree with the general parser on accepted
// rows, on error behaviour, and on statement atomicity.
#include "engine.hpp"
#include <chrono>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool ok, const std::string &what) {
  if (!ok) throw std::runtime_error("bulk insert check failed: " + what);
}
bool fails(mvdb::Engine &db, const std::string &sql) {
  try {
    db.execute(sql);
  } catch (const mvdb::Error &) {
    return true;
  }
  return false;
}
} // namespace

int main() {
  namespace fs = std::filesystem;
  const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
  const auto path = fs::temp_directory_path() /
                    ("mvdb-bulk-insert-" + std::to_string(nonce));
  try {
    mvdb::Engine db(path.string());
    db.execute("CREATE TABLE t(id BIGINT PRIMARY KEY,tag VARCHAR(8),v VECTOR(3));");
    // Plain multi-row values: handled by the fast path.
    auto result = db.execute(
        "INSERT INTO t VALUES (1,'a','[1,2,3]'),(2,'b','[4,5,6]');");
    require(result.affected == 2, "affected rows");
    // Column list in schema order: still the fast path.
    db.execute("INSERT INTO t(id,tag,v) VALUES (3,'c','[7,8,9]');");
    // Column list out of order: the parser path must still store canonical order.
    db.execute("INSERT INTO t(v,id,tag) VALUES ('[0,0,1]',4,'d');");
    // Escaped quote doubling is handled in place.
    db.execute("INSERT INTO t VALUES (5,'a''b','[0,0,0]');");
    // Backslash escapes fall back to the general parser.
    db.execute("INSERT INTO t VALUES (6,'a\\tb','[0,0,0]');");

    auto rows = db.execute("SELECT id,tag FROM t ORDER BY id;");
    require(rows.rows.size() == 6, "row count");
    require(std::get<std::string>(rows.rows[2].at(1)) == "c", "ordered column list");
    require(std::get<std::string>(rows.rows[3].at(1)) == "d", "reordered column list");
    require(std::get<std::string>(rows.rows[4].at(1)) == "a'b", "doubled quote");
    require(std::get<std::string>(rows.rows[5].at(1)) == "a\tb", "backslash escape");

    // A duplicate inside one statement fails and leaves nothing behind.
    require(fails(db, "INSERT INTO t VALUES (7,'x','[1,1,1]'),(7,'y','[2,2,2]');"),
            "duplicate key in statement");
    auto after = db.execute("SELECT id FROM t WHERE id=7;");
    require(after.rows.empty(), "failed statement left a row");
    // A type error mid-statement is atomic as well.
    require(fails(db, "INSERT INTO t VALUES (8,'z','[1,2,3]'),(9,'w','[1,2]');"),
            "dimension mismatch");
    auto partial = db.execute("SELECT id FROM t WHERE id=8;");
    require(partial.rows.empty(), "failed encode left a row");
    // Values outside the fast grammar still parse.
    db.execute("INSERT INTO t VALUES (10,'e','[ 1 , 2 , 3 ]');");
    auto spaced = db.execute("SELECT id FROM t WHERE id=10;");
    require(spaced.rows.size() == 1, "spaced vector literal");
    fs::remove_all(path);
    std::cout << "bulk insert fast path matches parser semantics\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << " (data retained at " << path << ")\n";
    return 1;
  }
}
