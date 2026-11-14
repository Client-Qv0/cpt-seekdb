#include "engine.hpp"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
int checks = 0;
void check(bool condition, const std::string& message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}
void error(mvdb::Engine& db, const std::string& sql) {
  try { db.execute(sql); }
  catch (const mvdb::Error&) { ++checks; return; }
  throw std::runtime_error("Expected failure: " + sql);
}
int64_t id(const mvdb::Result& r, size_t row) { return std::get<int64_t>(r.rows.at(row).at(0)); }
}

int main() {
  namespace fs = std::filesystem;
  auto path = fs::temp_directory_path() / ("mvdb-engine-extra-" + std::to_string(
      std::chrono::steady_clock::now().time_since_epoch().count()));
  try {
    {
      mvdb::Engine db(path.string());
      db.execute("CREATE TABLE t(id BIGINT PRIMARY KEY,n BIGINT,s VARCHAR(1),v VECTOR(2))");
      db.execute("INSERT INTO t VALUES (-9223372036854775808,-9223372036854775808,'🙂','[16777217,0]'),(9223372036854775807,9223372036854775807,'中','[16777216,1]'),(3,0,'a','[0,0]'),(4,0,'α','[0,0]')");
      auto r = db.execute("SELECT id,n FROM t ORDER BY id");
      check(r.rows.size() == 4 && id(r,0) == INT64_MIN && id(r,3) == INT64_MAX,"BIGINT ordering must preserve endpoints");
      check(std::get<int64_t>(r.rows[0][1]) == INT64_MIN && std::get<int64_t>(r.rows[3][1]) == INT64_MAX,"BIGINT endpoints must survive serialization");
      r = db.execute("SELECT id FROM t ORDER BY s");
      check(id(r,0) == 3 && id(r,1) == 4 && id(r,2) == INT64_MAX && id(r,3) == INT64_MIN,"VARCHAR must sort by Unicode code points");
      r = db.execute("SELECT id FROM t WHERE s < 'zz' ORDER BY id");
      check(r.rows.size() == 1 && id(r,0) == 3,"Comparison literals must not inherit VARCHAR storage length limits");
      r = db.execute("SELECT id,v,L2_DISTANCE(v,'[16777216,0]') AS d FROM t WHERE id=-9223372036854775808");
      check(std::get<std::vector<float>>(r.rows[0][1])[0] == 16777216.0f,"Vector must round to float32 before storage");
      check(std::get<double>(r.rows[0][2]) == 0.0,"L2 distance must use stored float32, not original decimal");
      r = db.execute("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM t ORDER BY d LIMIT 2");
      check(r.rows.size() == 2 && id(r,0) == 3 && id(r,1) == 4,"Distance ties must use ascending primary key");
      r = db.execute("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM t WHERE s='中' ORDER BY d LIMIT 1");
      check(r.rows.size() == 1 && id(r,0) == INT64_MAX,"Filter must precede TopK selection");
      r = db.execute("SELECT id FROM t ORDER BY n DESC LIMIT 3");
      check(id(r,0) == INT64_MAX && id(r,1) == 3 && id(r,2) == 4,"Descending scalar sort must still use ascending PK ties");
      r = db.execute("SELECT id FROM t WHERE id > 0 ORDER BY id LIMIT 100");
      check(r.rows.size() == 3,"TopK with too few matches must return all matches");
      r = db.execute("SELECT id FROM t WHERE id=9 LIMIT 10"); check(r.rows.empty(),"Empty filtered set must stay empty");
      error(db,"INSERT INTO t VALUES(8,9223372036854775808,'x','[0,0]')");
      error(db,"INSERT INTO t VALUES(8,-9223372036854775809,'x','[0,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'ab','[0,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[3.5e38,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[NaN,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[Infinity,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[0,0,0]')");
      error(db,"INSERT INTO t VALUES(8,0,'x','[0,0,]')");
      std::string bad_utf8 = "INSERT INTO t VALUES(8,0,'";
      bad_utf8 += char(0xc0); bad_utf8 += char(0xaf); bad_utf8 += "','[0,0]')";
      error(db,bad_utf8);
      error(db,"SELECT id FROM t ORDER BY v");
      error(db,"UPDATE t SET id=10 WHERE id=3");
      db.execute("BEGIN");
      db.execute("INSERT INTO t VALUES(5,0,'x','[2,2]')");
      error(db,"INSERT INTO t VALUES(6,0,'x','[1,1]'),(7,0,'too long','[1,1]')");
      r = db.execute("SELECT id FROM t WHERE id>=5 AND id<=7 ORDER BY id");
      check(r.rows.size() == 1 && id(r,0) == 5,"Statement failure must undo its own partial writes, preserve earlier transaction writes");
      db.execute("UPDATE t SET v='[1,1]' WHERE id=5");
      r = db.execute("SELECT id,L2_DISTANCE(v,'[1,1]') AS d FROM t ORDER BY d LIMIT 1");
      check(id(r,0) == 5,"Vector search must see transaction updates");
      const std::string compact_sql =
          "SELECT id,s,v,L2_DISTANCE(v,'[1,1]') AS d,"
          "L2_DISTANCE(v,'[9,9]') AS other FROM t ORDER BY d LIMIT 3";
      const auto first_compact = db.execute(compact_sql);
      const auto cached_compact = db.execute(compact_sql);
      check(first_compact.rows == cached_compact.rows,
            "Compact winner projection must match the first-scan output");
      check(id(cached_compact,0) == 5 &&
                std::get<std::string>(cached_compact.rows[0][1]) == "x" &&
                std::get<std::vector<float>>(cached_compact.rows[0][2]) ==
                    std::vector<float>{1,1} &&
                std::get<double>(cached_compact.rows[0][3]) == 0 &&
                std::get<double>(cached_compact.rows[0][4]) ==
                    std::sqrt(128.0),
            "Compact output must materialize scalar, text, vector and distances");
      db.execute("UPDATE t SET s='z',v='[9,9]' WHERE id=5");
      r = db.execute("SELECT id,s,v,L2_DISTANCE(v,'[9,9]') AS d FROM t "
                     "ORDER BY d LIMIT 1");
      check(id(r,0) == 5 && std::get<std::string>(r.rows[0][1]) == "z" &&
                std::get<std::vector<float>>(r.rows[0][2]) ==
                    std::vector<float>{9,9} &&
                std::get<double>(r.rows[0][3]) == 0,
            "Compact output must be invalidated by transaction updates");
      db.execute("UPDATE t SET s='x',v='[1,1]' WHERE id=5");
      db.execute("COMMIT");
      db.execute("CREATE VECTOR INDEX vi ON t(v)");
      db.execute("BEGIN");
      db.execute("DELETE FROM t WHERE id=5");
      db.execute("UPDATE t SET v='[9,9]' WHERE id=3");
      db.execute("ROLLBACK");
      r = db.execute("SELECT id,L2_DISTANCE(v,'[1,1]') AS d FROM t ORDER BY d LIMIT 1");
      check(id(r,0) == 5,"Rollback must restore visible vectors and deleted rows");
      db.execute("BEGIN");
      db.execute("INSERT INTO t VALUES(6,0,'z','[0,0]')");
      // Destruction is a clean shutdown with an uncommitted transaction.
    }
    {
      mvdb::Engine db(path.string());
      auto r = db.execute("SELECT id FROM t WHERE id>=5 AND id<=7 ORDER BY id");
      check(r.rows.size() == 1 && id(r,0) == 5,"Reopen must preserve commits and discard uncommitted changes");
      r = db.execute("SELECT id,L2_DISTANCE(v,'[1,1]') AS d FROM t ORDER BY d LIMIT 1");
      check(id(r,0) == 5,"Vector search must remain consistent across restart");
      error(db,"CREATE VECTOR INDEX vi ON t(v)");
    }
    {
      // TopK wider than the retired 4096 cap. The data makes the expected order
      // checkable: distance is i%1000, so ties fall back to ascending id.
      mvdb::Engine db(path.string() + "-cap");
      db.execute("CREATE TABLE cap(id BIGINT PRIMARY KEY,v VECTOR(4))");
      for (int begin = 0; begin < 5000; begin += 100) {
        std::string values;
        for (int i = begin; i < begin + 100; ++i) {
          if (!values.empty()) values += ',';
          values += "(" + std::to_string(i) + ",'[" + std::to_string(i % 1000) + ",0,0,0]')";
        }
        db.execute("INSERT INTO cap VALUES " + values);
      }
      auto wide = db.execute("SELECT id,L2_DISTANCE(v,'[0,0,0,0]') AS d FROM cap ORDER BY d LIMIT 5000");
      check(wide.rows.size() == 5000,"TopK above the retired cap must return every row");
      bool ordered = true;
      for (size_t i = 1; i < wide.rows.size(); ++i) {
        const double a = std::get<double>(wide.rows[i - 1][1]);
        const double b = std::get<double>(wide.rows[i][1]);
        if (a > b || (a == b && id(wide, i - 1) > id(wide, i))) { ordered = false; break; }
      }
      check(ordered,"TopK above the retired cap must keep distance then key order");
      auto narrow = db.execute("SELECT id,L2_DISTANCE(v,'[0,0,0,0]') AS d FROM cap ORDER BY d LIMIT 4100");
      check(narrow.rows.size() == 4100,"A narrower TopK must still cap the result");
      bool prefix = true;
      for (size_t i = 0; i < narrow.rows.size(); ++i)
        if (narrow.rows[i] != wide.rows[i]) { prefix = false; break; }
      check(prefix,"A narrower TopK must be a prefix of a wider one");
    }
    {
      // A descending distance key keeps the farthest rows, while ties still
      // resolve by ascending primary key like the path that projects every row.
      mvdb::Engine db(path.string() + "-desc");
      db.execute("CREATE TABLE d1(id BIGINT PRIMARY KEY,v VECTOR(2))");
      db.execute("INSERT INTO d1 VALUES (1,'[0,0]'),(2,'[1,0]'),(3,'[2,0]'),(4,'[3,0]'),(5,'[4,0]')");
      auto asc = db.execute("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM d1 ORDER BY d LIMIT 3");
      auto desc = db.execute("SELECT id,L2_DISTANCE(v,'[0,0]') AS d FROM d1 ORDER BY d DESC LIMIT 3");
      check(asc.rows.size() == 3 && desc.rows.size() == 3,"both directions must respect the limit");
      check(id(asc,0) == 1 && id(asc,2) == 3,"ascending TopK must start at the nearest row");
      check(id(desc,0) == 5 && id(desc,1) == 4 && id(desc,2) == 3,
            "descending TopK must start at the farthest row");
    }
    fs::remove_all(path.string() + "-desc");
    fs::remove_all(path.string() + "-cap");
    fs::remove_all(path);
    std::cout << "engine extra checks passed: " << checks << '\n';
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << " (data retained at " << path << ")\n";
    return 1;
  }
}
