// Parallel exact scan must produce byte-identical results at every width, keep
// the merged tie order by ascending primary key, and actually engage the worker
// pool for large tables.
#include "engine.hpp"
#include "exact_cache.hpp"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using mvdb::Cell;

void require(bool ok, const std::string &what) {
  if (!ok) throw std::runtime_error(what);
}

std::string vector_sql(int64_t key) {
  std::ostringstream out;
  out << '[' << std::setprecision(9);
  for (int d = 0; d < 16; ++d) {
    if (d) out << ',';
    // Only 97 distinct patterns so several rows share an exact distance.
    const int64_t bucket = key % 97;
    const double value = std::sin(double(bucket) * 0.37 + d * 0.71);
    out << value;
  }
  out << ']';
  return out.str();
}

std::string query_sql(size_t index, bool filtered) {
  std::ostringstream out;
  out << "SELECT id,L2_DISTANCE(v,'[";
  for (int d = 0; d < 16; ++d) {
    if (d) out << ',';
    out << std::sin(double(index % 89) * 0.41 + d * 0.53);
  }
  out << "]') AS distance FROM p";
  if (filtered) out << " WHERE grp='" << (index % 4) << "'";
  out << " ORDER BY distance LIMIT " << (index % 3 == 0 ? 40 : 10) << ";";
  return out.str();
}

std::string serialize(const mvdb::Result &result) {
  std::ostringstream out;
  out << std::setprecision(17);
  for (const auto &column : result.columns) out << column << '|';
  out << '\n';
  for (const auto &row : result.rows) {
    for (const auto &cell : row) {
      if (const auto *i = std::get_if<int64_t>(&cell)) out << 'i' << *i;
      else if (const auto *s = std::get_if<std::string>(&cell)) out << 's' << s->size() << ':' << *s;
      else if (const auto *d = std::get_if<double>(&cell)) out << 'd' << *d;
      else if (const auto *v = std::get_if<std::vector<float>>(&cell)) {
        out << 'v';
        for (float f : *v) out << f << ',';
      }
      out << ';';
    }
    out << '\n';
  }
  return out.str();
}

std::vector<std::string> run_suite(mvdb::Engine &db) {
  std::vector<std::string> out;
  for (size_t i = 0; i < 24; ++i) out.push_back(serialize(db.execute(query_sql(i, false))));
  for (size_t i = 0; i < 24; ++i) out.push_back(serialize(db.execute(query_sql(i, true))));
  return out;
}
} // namespace

int main() {
  namespace fs = std::filesystem;
  const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
  const auto path = fs::temp_directory_path() /
                    ("mvdb-parallel-search-" + std::to_string(nonce));
  try {
    {
      mvdb::Engine db(path.string());
      db.execute("CREATE TABLE p(id BIGINT PRIMARY KEY,grp VARCHAR(8),v VECTOR(16));");
      for (int start = 0; start < 12000; start += 200) {
        std::ostringstream sql;
        sql << "INSERT INTO p VALUES ";
        for (int id = start; id < start + 200; ++id) {
          if (id != start) sql << ',';
          sql << '(' << id << ",'" << (id % 4) << "','" << vector_sql(id) << "')";
        }
        sql << ';';
        db.execute(sql.str());
      }
      db.execute("CREATE VECTOR INDEX p_v ON p(v);");
    }
    mvdb::Engine db(path.string());
    mvdb::exact::set_thread_limit(1);
    const auto serial = run_suite(db);
    const size_t runs_before = mvdb::exact::parallel_runs();
    for (size_t width : {1u, 2u, 3u, 4u, 2u}) {
      mvdb::exact::set_thread_limit(width);
      const auto parallel = run_suite(db);
      require(parallel.size() == serial.size(), "result count changed");
      for (size_t i = 0; i < serial.size(); ++i)
        require(parallel[i] == serial[i],
                "result differs at width " + std::to_string(width) +
                    " query " + std::to_string(i));
      if (width > 1)
        require(mvdb::exact::parallel_runs() > runs_before,
                "worker pool was never engaged at width " + std::to_string(width));
    }
    // Every returned key must be unique and ordered by (distance, id).
    mvdb::exact::set_thread_limit(2);
    for (size_t i = 0; i < 24; ++i) {
      const auto result = db.execute(query_sql(i, false));
      std::set<int64_t> seen;
      double previous = -1;
      for (const auto &row : result.rows) {
        const int64_t id = std::get<int64_t>(row.at(0));
        const double distance = std::get<double>(row.at(1));
        require(seen.insert(id).second, "duplicate key in parallel result");
        require(distance >= previous, "parallel result is not sorted");
        previous = distance;
      }
    }
    fs::remove_all(path);
    std::cout << "parallel exact scan determinism and merge ordering passed\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << " (data retained at " << path << ")\n";
    return 1;
  }
}
