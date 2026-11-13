#include "engine.hpp"
#include "exact_cache.hpp"
#include "spill.hpp"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <functional>
#include <iomanip>
#include <limits>
#include <locale>
#include <mutex>
#include <queue>
#include <set>
#include <sstream>
#include <thread>
#if defined(__linux__)
#include <sched.h>
#endif

namespace mvdb {
namespace {
// CPUs this process may actually run on. The official checker fixes the CPU
// set, so the affinity mask is a better guide than the host core count.
size_t usable_cpus() {
#if defined(__linux__)
  cpu_set_t set;
  CPU_ZERO(&set);
  if (sched_getaffinity(0, sizeof(set), &set) == 0) {
    const int count = CPU_COUNT(&set);
    if (count > 0) return static_cast<size_t>(count);
  }
#endif
  const size_t count = std::thread::hardware_concurrency();
  return count ? count : 1;
}
// Statements execute one at a time, so a fixed pool of idle workers is enough:
// a query publishes one body and waits for the participating workers.
class WorkerPool {
public:
  static WorkerPool &instance() {
    static WorkerPool pool;
    return pool;
  }
  size_t capacity() const { return threads_.size() + 1; }
  void run(size_t width, const std::function<void(size_t)> &body) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (width < 2 || width > capacity()) {
      lock.unlock();
      body(0);
      return;
    }
    body_ = &body;
    width_ = width;
    pending_ = width - 1;
    failure_ = nullptr;
    ++generation_;
    cv_.notify_all();
    lock.unlock();
    try {
      body(0);
    } catch (...) {
      lock.lock();
      failure_ = std::current_exception();
      lock.unlock();
    }
    lock.lock();
    done_.wait(lock, [this] { return pending_ == 0; });
    body_ = nullptr;
    const std::exception_ptr failure = failure_;
    pending_ = 0;
    lock.unlock();
    if (failure) std::rethrow_exception(failure);
  }

private:
  WorkerPool() {
    const size_t count = std::min<size_t>(usable_cpus(), 4);
    for (size_t index = 1; index < count; ++index)
      threads_.emplace_back([this, index] { work(index); });
  }
  ~WorkerPool() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
      ++generation_;
    }
    cv_.notify_all();
    for (auto &thread : threads_) thread.join();
  }
  WorkerPool(const WorkerPool &) = delete;
  WorkerPool &operator=(const WorkerPool &) = delete;
  void work(size_t index) {
    size_t seen = 0;
    std::unique_lock<std::mutex> lock(mutex_);
    for (;;) {
      cv_.wait(lock, [&] { return stopping_ || generation_ != seen; });
      if (stopping_) return;
      seen = generation_;
      if (index >= width_) continue;
      const std::function<void(size_t)> *body = body_;
      lock.unlock();
      std::exception_ptr failure;
      try {
        (*body)(index);
      } catch (...) {
        failure = std::current_exception();
      }
      lock.lock();
      if (failure && !failure_) failure_ = failure;
      if (--pending_ == 0) done_.notify_one();
    }
  }
  std::vector<std::thread> threads_;
  std::mutex mutex_;
  std::condition_variable cv_;
  std::condition_variable done_;
  const std::function<void(size_t)> *body_ = nullptr;
  std::exception_ptr failure_;
  size_t width_ = 1;
  size_t pending_ = 0;
  size_t generation_ = 0;
  bool stopping_ = false;
};
// Rows below this stay serial: pool wake-up would cost more than the scan.
constexpr size_t parallel_scan_min_rows = 1024;
size_t scan_width(size_t rows) {
  size_t width = exact::thread_limit();
  if (width == 0) width = usable_cpus();
  width = std::min<size_t>(width, 4);
  if (width < 2 || rows < parallel_scan_min_rows) return 1;
  return width;
}
struct Schema {
  std::vector<Column> columns;
  std::vector<std::pair<std::string, std::string>> indexes;
};
void u32(std::string &out, uint32_t x) {
  for (int i = 0; i < 4; ++i)
    out.push_back(char(x >> (8 * i)));
}
void u64(std::string &out, uint64_t x) {
  for (int i = 0; i < 8; ++i)
    out.push_back(char(x >> (8 * i)));
}
void bytes(std::string &out, const std::string &s) {
  if (s.size() > UINT32_MAX)
    throw Error("RESOURCE", "value exceeds serialization limit");
  u32(out, static_cast<uint32_t>(s.size()));
  out += s;
}
struct Reader {
  const std::string &s;
  size_t pos = 0;
  void need(size_t n) {
    if (n > s.size() - pos)
      throw Error("CORRUPTION", "invalid record encoding");
  }
  uint64_t num(int n) {
    need(n);
    uint64_t x = 0;
    for (int i = 0; i < n; ++i)
      x |= uint64_t(uint8_t(s[pos++])) << (8 * i);
    return x;
  }
  std::string str() {
    auto n = num(4);
    need(n);
    auto t = s.substr(pos, n);
    pos += n;
    return t;
  }
  void end() {
    if (pos != s.size())
      throw Error("CORRUPTION", "trailing record data");
  }
};
std::string pack_schema(const Schema &s) {
  std::string out = "MVS1";
  u32(out, s.columns.size());
  for (auto &c : s.columns) {
    bytes(out, c.name);
    u32(out, static_cast<uint32_t>(c.type));
    u32(out, c.size);
    u32(out, c.primary);
  }
  u32(out, s.indexes.size());
  for (auto &i : s.indexes) {
    bytes(out, i.first);
    bytes(out, i.second);
  }
  return out;
}
Schema unpack_schema(const std::string &s) {
  Reader r{s};
  r.need(4);
  if (s.substr(0, 4) != "MVS1")
    throw Error("CORRUPTION", "unknown schema version");
  r.pos = 4;
  Schema out;
  auto n = r.num(4);
  if (n > 65536)
    throw Error("CORRUPTION", "invalid column count");
  for (uint64_t i = 0; i < n; ++i) {
    Column c;
    c.name = r.str();
    auto t = r.num(4);
    if (t > 2)
      throw Error("CORRUPTION", "invalid type");
    c.type = static_cast<Type>(t);
    c.size = r.num(4);
    c.primary = r.num(4) != 0;
    out.columns.push_back(c);
  }
  auto ni = r.num(4);
  if (ni > 65536)
    throw Error("CORRUPTION", "invalid index count");
  for (uint64_t i = 0; i < ni; ++i) {
    auto name = r.str();
    auto col = r.str();
    out.indexes.emplace_back(name, col);
  }
  r.end();
  return out;
}
size_t col_index(const Schema &s, const std::string &name) {
  for (size_t i = 0; i < s.columns.size(); ++i)
    if (s.columns[i].name == name)
      return i;
  throw Error("COLUMN", "unknown column: " + name);
}
size_t primary_index(const Schema &s) {
  for (size_t i = 0; i < s.columns.size(); ++i)
    if (s.columns[i].primary)
      return i;
  throw Error("CORRUPTION", "missing primary key");
}
size_t utf8_count(const std::string &s) {
  size_t n = 0;
  for (size_t i = 0; i < s.size(); ++n) {
    uint8_t b = s[i++];
    uint32_t cp;
    int more;
    if (b < 0x80) {
      cp = b;
      more = 0;
    } else if (b >= 0xc2 && b <= 0xdf) {
      cp = b & 31;
      more = 1;
    } else if (b >= 0xe0 && b <= 0xef) {
      cp = b & 15;
      more = 2;
    } else if (b >= 0xf0 && b <= 0xf4) {
      cp = b & 7;
      more = 3;
    } else
      throw Error("TYPE", "invalid UTF-8");
    if (s.size() - i < static_cast<size_t>(more))
      throw Error("TYPE", "truncated UTF-8");
    for (int j = 0; j < more; ++j) {
      b = s[i++];
      if ((b & 0xc0) != 0x80)
        throw Error("TYPE", "invalid UTF-8 continuation");
      cp = (cp << 6) | (b & 63);
    }
    if ((more == 1 && cp < 0x80) || (more == 2 && cp < 0x800) ||
        (more == 3 && cp < 0x10000) || cp > 0x10ffff ||
        (cp >= 0xd800 && cp <= 0xdfff))
      throw Error("TYPE", "invalid Unicode scalar");
  }
  return n;
}
std::vector<float> vector_literal(const Literal &l, uint32_t dim) {
  if (!l.quoted)
    throw Error("TYPE", "VECTOR requires a quoted array");
  const auto &s = l.text;
  size_t p = 0;
  auto space = [&] {
    while (p < s.size() &&
           (s[p] == ' ' || s[p] == '\t' || s[p] == '\r' || s[p] == '\n'))
      ++p;
  };
  space();
  if (p == s.size() || s[p++] != '[')
    throw Error("TYPE", "expected vector array");
  space();
  std::vector<float> v;
  if (p < s.size() && s[p] != ']')
    for (;;) {
      size_t start = p;
      if (p < s.size() && (s[p] == '-' || s[p] == '+'))
        ++p;
      size_t digits = 0;
      while (p < s.size() && s[p] >= '0' && s[p] <= '9') {
        ++p;
        ++digits;
      }
      if (p < s.size() && s[p] == '.') {
        ++p;
        while (p < s.size() && s[p] >= '0' && s[p] <= '9') {
          ++p;
          ++digits;
        }
      }
      if (!digits)
        throw Error("TYPE", "vector component must be a finite number");
      if (p < s.size() && (s[p] == 'e' || s[p] == 'E')) {
        ++p;
        if (p < s.size() && (s[p] == '-' || s[p] == '+'))
          ++p;
        size_t e = p;
        while (p < s.size() && s[p] >= '0' && s[p] <= '9')
          ++p;
        if (p == e)
          throw Error("TYPE", "invalid exponent");
      }
      const char *begin = s.data() + start;
      const char *last = s.data() + p;
      // Floating from_chars does not accept a leading '+'. The unchanged
      // scanner above has already validated the complete decimal token.
      if (*begin == '+')
        ++begin;
      float f = 0;
      const auto parsed = std::from_chars(begin, last, f, std::chars_format::general);
      if (parsed.ec != std::errc() || parsed.ptr != last) {
        // Preserve strtof's existing acceptance and rounding of finite
        // underflows (including signed zero), and its overflow diagnostics.
        auto token = s.substr(start, p - start);
        char *end = nullptr;
        f = std::strtof(token.c_str(), &end);
        if (end != token.c_str() + token.size())
          throw Error("TYPE", "vector component overflows finite float32");
      }
      if (!std::isfinite(f))
        throw Error("TYPE", "vector component overflows finite float32");
      v.push_back(f);
      if (v.size() > dim)
        throw Error("TYPE", "vector dimension mismatch");
      space();
      if (p < s.size() && s[p] == ',') {
        ++p;
        space();
        continue;
      }
      break;
    }
  if (p == s.size() || s[p++] != ']')
    throw Error("TYPE", "invalid vector array");
  space();
  if (p != s.size() || v.size() != dim)
    throw Error("TYPE", "vector dimension mismatch or trailing input");
  return v;
}
Cell convert(const Literal &l, const Column &c, bool storing = true) {
  if (c.type == Type::Varchar) {
    if (!l.quoted)
      throw Error("TYPE", "VARCHAR requires a string");
    const auto characters = utf8_count(l.text);
    if (storing && characters > c.size)
      throw Error("TYPE", "VARCHAR character limit exceeded");
    return l.text;
  }
  if (c.type == Type::Vector)
    return vector_literal(l, c.size);
  if (l.quoted)
    throw Error("TYPE", "BIGINT requires an integer literal");
  int64_t x = 0;
  const char *begin = l.text.data();
  const char *end = begin + l.text.size();
  if (begin != end && *begin == '+')
    ++begin;
  auto res = std::from_chars(begin, end, x);
  if (begin == end || res.ec != std::errc() || res.ptr != end)
    throw Error("TYPE", "invalid or overflowing BIGINT");
  return x;
}
std::string pack_row(const std::vector<Cell> &row, const Schema &s) {
  std::string out;
  for (size_t i = 0; i < row.size(); ++i) {
    auto &c = s.columns[i];
    if (c.type == Type::BigInt)
      u64(out, static_cast<uint64_t>(std::get<int64_t>(row[i])));
    else if (c.type == Type::Varchar)
      bytes(out, std::get<std::string>(row[i]));
    else
      for (float f : std::get<std::vector<float>>(row[i])) {
        uint32_t x;
        std::memcpy(&x, &f, 4);
        u32(out, x);
      }
  }
  return out;
}
std::vector<Cell> unpack_row(const std::string &data, const Schema &s) {
  Reader r{data};
  std::vector<Cell> row;
  row.reserve(s.columns.size());
  for (auto &c : s.columns) {
    if (c.type == Type::BigInt) {
      uint64_t bits = r.num(8);
      int64_t v;
      std::memcpy(&v, &bits, 8);
      row.emplace_back(v);
    } else if (c.type == Type::Varchar)
      row.emplace_back(r.str());
    else {
      std::vector<float> v;
      v.reserve(c.size);
      for (uint32_t j = 0; j < c.size; ++j) {
        uint32_t b = r.num(4);
        float f;
        std::memcpy(&f, &b, 4);
        v.push_back(f);
      }
      row.emplace_back(std::move(v));
    }
  }
  r.end();
  return row;
}
int compare(const Cell &a, const Cell &b) {
  if (a.index() != b.index())
    throw Error("TYPE", "incompatible comparison");
  if (auto x = std::get_if<int64_t>(&a)) {
    auto y = std::get<int64_t>(b);
    return (*x > y) - (*x < y);
  }
  if (auto x = std::get_if<std::string>(&a)) {
    auto &y = std::get<std::string>(b);
    return (*x > y) - (*x < y);
  }
  if (auto x = std::get_if<double>(&a)) {
    auto y = std::get<double>(b);
    return (*x > y) - (*x < y);
  }
  throw Error("TYPE", "VECTOR cannot be used as a scalar ordering key");
}
struct Filter {
  size_t column;
  std::string op;
  Cell value;
};
std::vector<Filter> filters(const Statement &st, const Schema &s) {
  std::vector<Filter> out;
  for (auto &f : st.conditions) {
    auto i = col_index(s, f.column);
    if (s.columns[i].type == Type::Vector)
      throw Error("TYPE", "scalar filter required");
    out.push_back({i, f.op, convert(f.value, s.columns[i], false)});
  }
  return out;
}
bool matches(const std::vector<Cell> &row, const std::vector<Filter> &f) {
  for (auto &q : f) {
    int cmp = compare(row[q.column], q.value);
    bool yes = q.op == "="    ? cmp == 0
               : q.op == "<"  ? cmp < 0
               : q.op == "<=" ? cmp <= 0
               : q.op == ">"  ? cmp > 0
               : q.op == ">=" ? cmp >= 0
                              : false;
    if (!yes)
      return false;
  }
  return true;
}
struct Projection {
  size_t col;
  bool distance = false;
  std::vector<float> query;
};
Cell project(const Projection &p, const std::vector<Cell> &row) {
  if (!p.distance)
    return row[p.col];
  const auto &a = std::get<std::vector<float>>(row[p.col]);
  double sum = 0;
  for (size_t i = 0; i < a.size(); ++i) {
    double d = double(a[i]) - double(p.query[i]);
    sum += d * d;
  }
  return std::sqrt(sum);
}
std::string escaped(const std::string &s) {
  std::string o = "\"";
  const char *hex = "0123456789abcdef";
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') {
      o += '\\';
      o += char(c);
    } else if (c < 32) {
      o += "\\u00";
      o += hex[c >> 4];
      o += hex[c & 15];
    } else
      o += char(c);
  }
  return o + '"';
}
void json_cell(std::ostream &out, const Cell &cell) {
  if (auto p = std::get_if<int64_t>(&cell))
    out << *p;
  else if (auto p = std::get_if<std::string>(&cell))
    out << escaped(*p);
  else if (auto p = std::get_if<double>(&cell))
    out << std::setprecision(17) << *p;
  else {
    auto &v = std::get<std::vector<float>>(cell);
    out << '[';
    for (size_t i = 0; i < v.size(); ++i) {
      if (i)
        out << ',';
      out << std::setprecision(9) << v[i];
    }
    out << ']';
  }
}
size_t cell_bytes(const Cell &cell) {
  size_t bytes = sizeof(Cell) + 32;
  if (auto p = std::get_if<std::string>(&cell))
    bytes += p->capacity();
  if (auto p = std::get_if<std::vector<float>>(&cell))
    bytes += p->capacity() * sizeof(float);
  return bytes;
}
std::string row_json(const std::vector<Cell> &row) {
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << '[';
  for (size_t i = 0; i < row.size(); ++i) {
    if (i)
      out << ',';
    json_cell(out, row[i]);
  }
  out << ']';
  return out.str();
}
void ordered_u64(std::string &out, uint64_t n) {
  for (int i = 7; i >= 0; --i)
    out.push_back(static_cast<char>(n >> (i * 8)));
}
void ordered_cell(std::string &out, const Cell &c, bool descending) {
  const size_t start = out.size();
  if (auto p = std::get_if<int64_t>(&c))
    ordered_u64(out, static_cast<uint64_t>(*p) ^ (uint64_t(1) << 63));
  else if (auto p = std::get_if<double>(&c)) {
    double x = *p == 0 ? 0 : *p;
    uint64_t bits;
    std::memcpy(&bits, &x, 8);
    ordered_u64(out, (bits >> 63) ? ~bits : (bits ^ (uint64_t(1) << 63)));
  } else if (auto p = std::get_if<std::string>(&c)) {
    for (unsigned char ch : *p) {
      out.push_back(static_cast<char>(ch));
      if (ch == 0)
        out.push_back(static_cast<char>(255));
    }
    out.push_back(0);
    out.push_back(0);
  } else
    throw Error("TYPE", "invalid sort key");
  if (descending)
    for (size_t i = start; i < out.size(); ++i)
      out[i] = static_cast<char>(~static_cast<unsigned char>(out[i]));
}
} // namespace

struct Engine::Cache {
  struct Entry {
    int64_t key;
    std::vector<Cell> row;
  };
  std::string table;
  std::vector<Entry> rows;
  std::unique_ptr<exact::Compact> exact_view;
  size_t exact_column = 0;
  bool exact_bypass = false;
  bool complete = false;
  size_t bytes = 0;
  static constexpr size_t budget = 12 * 1024 * 1024;
};
Engine::Engine(const std::string &directory)
    : store_(directory), directory_(directory),
      cache_(std::make_unique<Cache>()) {}
Engine::~Engine() = default;

void Engine::prepare_shutdown() {
  store_.close();
  *cache_ = Cache{};
}
Result Engine::execute_ann(const Statement &statement) {
  // Explicit correctness-first fallback: no approximate index exists yet.
  // Both modes currently use exact scans. This is not an ANN performance claim
  // or evidence that hidden tests accept the missing approximate index.
  return execute_statement(statement);
}
Result Engine::execute(const std::string &sql, SearchMode mode) {
  if (mode != SearchMode::Exact && mode != SearchMode::Ann)
    throw Error("PROTOCOL", "invalid search mode");
  auto st = parse_sql(sql);
  // Cached records never outlive a mutation or transaction boundary. Failed
  // statements also invalidate: their intermediate writes must not be reused.
  if (st.kind != Statement::Select)
    *cache_ = Cache{};
  if (st.kind == Statement::Begin) {
    store_.begin();
    return {};
  }
  if (st.kind == Statement::Commit) {
    store_.commit();
    return {};
  }
  if (st.kind == Statement::Rollback) {
    store_.rollback();
    return {};
  }
  if (st.kind == Statement::Select)
    return mode == SearchMode::Ann ? execute_ann(st) : execute_statement(st);
  store_.begin_statement();
  try {
    auto result = execute_statement(st);
    store_.finish_statement();
    return result;
  } catch (...) {
    store_.abort_statement();
    throw;
  }
}
Result Engine::execute_statement(const Statement &st) {
  Result result;
  result.reports_affected = st.kind == Statement::Insert ||
                            st.kind == Statement::Update ||
                            st.kind == Statement::Delete;
  if (st.kind == Statement::CreateTable) {
    if (store_.metadata(st.table))
      throw Error("TABLE_EXISTS", "table already exists");
    Schema s{st.schema, {}};
    size_t pk = 0, vec = 0;
    std::set<std::string> names;
    if (s.columns.empty())
      throw Error("SCHEMA", "table requires columns");
    for (auto &c : s.columns) {
      if (!names.insert(c.name).second)
        throw Error("SCHEMA", "duplicate column");
      if (c.primary) {
        ++pk;
        if (c.type != Type::BigInt)
          throw Error("SCHEMA", "primary key must be BIGINT");
      }
      if (c.type == Type::Vector)
        ++vec;
      if (c.type != Type::BigInt && c.size == 0)
        throw Error("SCHEMA", "type size must be positive");
    }
    if (pk != 1 || vec > 1)
      throw Error(
          "SCHEMA",
          "require one BIGINT primary key and at most one vector column");
    store_.set_metadata(st.table, pack_schema(s));
    return result;
  }
  auto meta = store_.metadata(st.table);
  if (!meta)
    throw Error("TABLE", "unknown table: " + st.table);
  auto schema = unpack_schema(*meta);
  auto pk = primary_index(schema);
  if (st.kind == Statement::CreateIndex) {
    auto ci = col_index(schema, st.index_column);
    if (schema.columns[ci].type != Type::Vector)
      throw Error("TYPE", "vector index requires VECTOR column");
    for (auto &i : schema.indexes)
      if (i.first == st.index_name)
        throw Error("INDEX_EXISTS", "index already exists");
    // Exact scan is the correctness-first index backend. No ANN claim is made.
    schema.indexes.emplace_back(st.index_name, st.index_column);
    store_.set_metadata(st.table, pack_schema(schema));
    return result;
  }
  if (st.kind == Statement::Insert) {
    std::vector<size_t> mapping;
    if (st.insert_columns.empty()) {
      for (size_t i = 0; i < schema.columns.size(); ++i)
        mapping.push_back(i);
    } else {
      std::set<size_t> seen;
      for (auto &name : st.insert_columns) {
        auto i = col_index(schema, name);
        if (!seen.insert(i).second)
          throw Error("COLUMN", "duplicate insertion column");
        mapping.push_back(i);
      }
      if (mapping.size() != schema.columns.size())
        throw Error("COLUMN",
                    "all columns must be provided; NULL/defaults unsupported");
    }
    for (auto &tuple : st.values) {
      if (tuple.size() != mapping.size())
        throw Error("TYPE", "column/value count mismatch");
      std::vector<Cell> row(schema.columns.size());
      for (size_t i = 0; i < tuple.size(); ++i)
        row[mapping[i]] = convert(tuple[i], schema.columns[mapping[i]]);
      auto key = std::get<int64_t>(row[pk]);
      if (store_.get(st.table, key))
        throw Error("DUPLICATE_KEY", "duplicate primary key");
      store_.put(st.table, key, pack_row(row, schema));
      ++result.affected;
    }
    return result;
  }
  auto fs = filters(st, schema);
  if (st.kind == Statement::Update || st.kind == Statement::Delete) {
    std::vector<std::pair<size_t, Cell>> assignments;
    std::set<size_t> seen;
    for (auto &a : st.assignments) {
      auto i = col_index(schema, a.first);
      if (i == pk)
        throw Error("UNSUPPORTED", "primary key update is unsupported");
      if (!seen.insert(i).second)
        throw Error("COLUMN", "duplicate assignment");
      assignments.emplace_back(i, convert(a.second, schema.columns[i]));
    }
    auto mutate = [&](int64_t key, const std::string &data) {
      auto row = unpack_row(data, schema);
      if (!matches(row, fs))
        return;
      if (st.kind == Statement::Delete)
        store_.erase(st.table, key);
      else {
        for (auto &a : assignments)
          row[a.first] = a.second;
        store_.put(st.table, key, pack_row(row, schema));
      }
      ++result.affected;
    };
    auto equality = std::find_if(fs.begin(), fs.end(), [&](const Filter &f) {
      return f.column == pk && f.op == "=";
    });
    if (equality != fs.end()) {
      const auto key = std::get<int64_t>(equality->value);
      if (auto data = store_.get(st.table, key))
        mutate(key, *data);
    } else
      store_.scan(st.table, mutate);
    return result;
  }
  if (st.kind != Statement::Select)
    throw Error("UNSUPPORTED", "unsupported operation");
  std::vector<Projection> ps;
  for (auto &e : st.projections) {
    if (e.kind == Expr::Star) {
      for (size_t i = 0; i < schema.columns.size(); ++i) {
        ps.push_back({i, false, {}});
        result.columns.push_back(schema.columns[i].name);
      }
      continue;
    }
    auto i = col_index(schema, e.column);
    Projection p{i, e.kind == Expr::Distance, {}};
    if (p.distance) {
      if (schema.columns[i].type != Type::Vector)
        throw Error("TYPE", "L2_DISTANCE requires VECTOR column");
      p.query = vector_literal(e.vector, schema.columns[i].size);
    }
    ps.push_back(std::move(p));
    result.columns.push_back(
        e.alias.empty() ? (e.kind == Expr::Distance ? "l2_distance" : e.column)
                        : e.alias);
  }
  struct SortKey {
    bool projection;
    size_t index;
    bool desc;
  };
  std::vector<SortKey> keys;
  for (auto &o : st.order) {
    size_t found = result.columns.size();
    for (size_t i = 0; i < result.columns.size(); ++i)
      if (result.columns[i] == o.name) {
        if (found != result.columns.size())
          throw Error("COLUMN", "ambiguous order alias");
        found = i;
      }
    if (found != result.columns.size()) {
      if (!ps[found].distance &&
          schema.columns[ps[found].col].type == Type::Vector)
        throw Error("TYPE", "cannot order by VECTOR");
      keys.push_back({true, found, o.descending});
    } else {
      auto i = col_index(schema, o.name);
      if (schema.columns[i].type == Type::Vector)
        throw Error("TYPE", "cannot order by VECTOR");
      keys.push_back({false, i, o.descending});
    }
  }
  auto scan_rows = [&](auto &&visitor) {
    auto equality = std::find_if(fs.begin(), fs.end(), [&](const Filter &f) {
      return f.column == pk && f.op == "=";
    });
    if (equality != fs.end()) {
      const auto key = std::get<int64_t>(equality->value);
      if (auto data = store_.get(st.table, key))
        visitor(key, unpack_row(*data, schema));
      return;
    }
    if (cache_->table == st.table && cache_->complete) {
      for (const auto &entry : cache_->rows)
        visitor(entry.key, entry.row);
      return;
    }
    bool collecting = cache_->table != st.table;
    if (collecting) {
      *cache_ = Cache{};
      cache_->table = st.table;
    }
    try {
      store_.scan(st.table, [&](int64_t key, const std::string &data) {
        auto row = unpack_row(data, schema);
        visitor(key, row);
        if (collecting) {
          size_t size = sizeof(Cache::Entry) * 2;
          for (const auto &cell : row)
            size += cell_bytes(cell);
          if (size > Cache::budget - cache_->bytes) {
            cache_->rows = {};
            std::vector<Cache::Entry>().swap(cache_->rows);
            cache_->bytes = 0;
            collecting = false;
          } else {
            cache_->bytes += size;
            cache_->rows.push_back({key, std::move(row)});
          }
        }
      });
      cache_->complete = collecting;
    } catch (...) {
      *cache_ = Cache{};
      throw;
    }
  };
  if (st.limit && *st.limit == 0)
    return result;
  // The common exact vector TopK path keeps only (distance, primary key) while
  // searching. Materialize projections for winners, not for every scanned row.
  size_t projection_bound = 0;
  for (const auto &p : ps) {
    const auto &c = schema.columns[p.col];
    projection_bound += sizeof(Cell) + 32 +
                        (p.distance                ? 0
                         : c.type == Type::Vector  ? size_t(c.size) * 4
                         : c.type == Type::Varchar ? size_t(c.size) * 4
                                                   : 0);
  }
  constexpr size_t result_budget = 4 * 1024 * 1024;
  if (st.limit && *st.limit <= 4096 && keys.size() == 1 && !keys[0].desc &&
      keys[0].projection && ps[keys[0].index].distance &&
      projection_bound <= result_budget / *st.limit) {
    struct Neighbor {
      double distance;
      int64_t key;
      size_t row;
    };
    auto better_neighbor = [](const Neighbor &a, const Neighbor &b) {
      return a.distance < b.distance ||
             (a.distance == b.distance && a.key < b.key);
    };
    std::priority_queue<Neighbor, std::vector<Neighbor>,
                        decltype(better_neighbor)>
        nearest(better_neighbor);
    using Heap = decltype(nearest);
    const auto &projection = ps[keys[0].index];
    auto consider = [&](Heap &heap, int64_t key, double distance,
                        size_t row = std::numeric_limits<size_t>::max()) {
      Neighbor n{distance, key, row};
      if (heap.size() < *st.limit)
        heap.push(n);
      else if (better_neighbor(n, heap.top())) {
        heap.pop();
        heap.push(n);
      }
    };
    auto original_visit = [&](int64_t key, const std::vector<Cell> &row) {
      if (matches(row, fs))
        consider(nearest, key, std::get<double>(project(projection, row)));
    };
    const bool point_lookup = std::any_of(fs.begin(), fs.end(), [&](const Filter &f) {
      return f.column == pk && f.op == "=";
    });
    const exact::Compact *winner_view = nullptr;
    if (exact::available() && !point_lookup && st.table.size() <= 1024) {
      if (cache_->table != st.table || cache_->exact_column != projection.col ||
          cache_->complete) {
        *cache_ = Cache{};
        cache_->table = st.table;
        cache_->exact_column = projection.col;
      }
      if (cache_->exact_view) {
        auto &view = *cache_->exact_view;
        winner_view = &view;
        const bool screen=exact::fp32_screen_available(view.dim);
        auto quantized=exact::prepare_quantized_query(view,projection.query,screen);
        // One contiguous slice of the packed scan. Each slice keeps its own
        // heap, so slices run on separate threads without shared mutable state.
        // A slice's screening threshold comes from its own heap and is therefore
        // more permissive than the merged one: extra candidates can survive, but
        // a row that belongs in the top K is never screened out.
        auto scan_contiguous = [&](size_t begin, size_t end, Heap &heap) {
          double screened_worst = -1, screen_threshold = 0;
          size_t i = begin;
          for (; i + 8 <= end;) {
            size_t batch_count = 8;
            if (screen && heap.size() == *st.limit) {
              if (i + 32 <= end) batch_count = 32;
              const double worst = heap.top().distance;
              if (worst != screened_worst) {
                screen_threshold = quantized.codes
                    ? exact::quantized_threshold(worst, view.quantized_step,
                                                  quantized.root_dim_upper)
                    : exact::fp32_screen_threshold(worst, view.dim);
                screened_worst = worst;
              }
              uint32_t survivors = 0;
              if (quantized.codes) {
                for (size_t lane = 0; lane < batch_count; ++lane)
                  if (!(double(exact::quantized_squared_distance(
                            view, i + lane, quantized)) > screen_threshold))
                    survivors |= uint32_t(1) << lane;
              } else {
                float approximate[32];
                if (batch_count == 32)
                  exact::squared_distances32_fp32_contiguous(
                      view, i, projection.query, approximate);
                else
                  exact::squared_distances8_fp32_contiguous(
                      view, i, projection.query, approximate);
                for (size_t lane = 0; lane < batch_count; ++lane)
                  if (!exact::fp32_screen_reject(approximate[lane],
                                                 screen_threshold))
                    survivors |= uint32_t(1) << lane;
              }
              const uint32_t all =
                  batch_count == 32 ? uint32_t(0xffffffffu) : uint32_t(0xffu);
              if (survivors != all) {
                for (size_t lane = 0; lane < batch_count; ++lane)
                  if (survivors & (uint32_t(1) << lane))
                    consider(heap, view.keys[i + lane],
                             view.distance(i + lane, projection.query), i + lane);
                // A threshold captured before this batch is conservative even
                // if refinement improves the heap; refresh it for the next batch.
                i += batch_count;
                continue;
              }
            }
            // Heap initialization, unsupported FP modes, and all-surviving
            // batches retain the original eight-record double computation.
            for (size_t offset = 0; offset < batch_count; offset += 8) {
              double distances[8];
              exact::distances8_contiguous(view, i + offset, projection.query,
                                           distances);
              for (size_t lane = 0; lane < 8; ++lane)
                consider(heap, view.keys[i + offset + lane], distances[lane],
                         i + offset + lane);
            }
            i += batch_count;
          }
          if (i + 4 <= end) {
            const size_t rows[4] = {i, i + 1, i + 2, i + 3};
            double distances[4];
            exact::distances4(view, rows, projection.query, distances);
            for (size_t lane = 0; lane < 4; ++lane)
              consider(heap, view.keys[i + lane], distances[lane], i + lane);
            i += 4;
          }
          for (; i < end; ++i)
            consider(heap, view.keys[i], view.distance(i, projection.query), i);
        };
        // Batched scan of an explicit candidate list. Non-contiguous rows keep
        // the gather-based float32 screen for 32 rows at a time; the posting
        // array stays uint32 and only the active batch is widened.
        auto scan_list = [&](const uint32_t *rows, size_t count, Heap &heap) {
          if (!count) return;
          double screened_worst = -1, screen_threshold = 0;
          auto refine = [&](const size_t *batch, size_t lanes) {
            size_t offset = 0;
            for (; offset + 8 <= lanes; offset += 8) {
              double distances[8];
              const size_t rows[8] = {batch[offset], batch[offset + 1],
                                      batch[offset + 2], batch[offset + 3],
                                      batch[offset + 4], batch[offset + 5],
                                      batch[offset + 6], batch[offset + 7]};
              exact::distances8(view, rows, projection.query, distances);
              for (size_t lane = 0; lane < 8; ++lane)
                consider(heap, view.keys[rows[lane]], distances[lane],
                         rows[lane]);
            }
            for (size_t lane = offset; lane < lanes; ++lane)
              consider(heap, view.keys[batch[lane]],
                       view.distance(batch[lane], projection.query), batch[lane]);
          };
          size_t at = 0;
          for (; at + 32 <= count; at += 32) {
            size_t batch[32];
            for (size_t lane = 0; lane < 32; ++lane) batch[lane] = rows[at + lane];
            if (screen && heap.size() == *st.limit) {
              const double worst = heap.top().distance;
              if (worst != screened_worst) {
                screen_threshold = quantized.codes
                    ? exact::quantized_threshold(worst, view.quantized_step,
                                                  quantized.root_dim_upper)
                    : exact::fp32_screen_threshold(worst, view.dim);
                screened_worst = worst;
              }
              uint32_t survivors = 0;
              if (quantized.codes) {
                for (size_t lane = 0; lane < 32; ++lane)
                  if (!(double(exact::quantized_squared_distance(
                            view, batch[lane], quantized)) > screen_threshold))
                    survivors |= uint32_t(1) << lane;
              } else {
                float approximate[32];
                exact::squared_distances32_fp32(view, batch, projection.query,
                                                approximate);
                for (size_t lane = 0; lane < 32; ++lane)
                  if (!exact::fp32_screen_reject(approximate[lane],
                                                 screen_threshold))
                    survivors |= uint32_t(1) << lane;
              }
              if (survivors != uint32_t(0xffffffffu)) {
                for (size_t lane = 0; lane < 32; ++lane)
                  if (survivors & (uint32_t(1) << lane))
                    consider(heap, view.keys[batch[lane]],
                             view.distance(batch[lane], projection.query),
                             batch[lane]);
                continue;
              }
            }
            refine(batch, 32);
          }
          size_t tail[32];
          const size_t remaining = count - at;
          for (size_t lane = 0; lane < remaining; ++lane) tail[lane] = rows[at + lane];
          refine(tail, remaining);
        };
        // Split the scan into contiguous slices and merge the per-slice heaps.
        // Neighbor comparison is a total order on (distance, primary key), so
        // the merged top K is identical to the serial one at every width.
        auto run_slices = [&](
            size_t total,
            const std::function<void(size_t, size_t, Heap &)> &body) {
          const size_t width = scan_width(total);
          if (width < 2) {
            body(0, total, nearest);
            return;
          }
          std::vector<Heap> heaps;
          heaps.reserve(width);
          for (size_t index = 0; index < width; ++index)
            heaps.emplace_back(better_neighbor);
          const size_t per = (total + width - 1) / width;
          const size_t chunk = (per + 31) / 32 * 32;
          WorkerPool::instance().run(width, [&](size_t index) {
            const size_t begin = std::min(total, index * chunk);
            const size_t end = std::min(total, begin + chunk);
            if (begin < end) body(begin, end, heaps[index]);
          });
          for (auto &heap : heaps)
            while (!heap.empty()) {
              const Neighbor neighbor = heap.top();
              heap.pop();
              consider(nearest, neighbor.key, neighbor.distance, neighbor.row);
            }
          ++exact::parallel_runs();
        };
        if (fs.empty()) {
          run_slices(static_cast<size_t>(view.count),
                     [&](size_t begin, size_t end, Heap &heap) {
                       scan_contiguous(begin, end, heap);
                     });
        } else {
          auto eligible = [&](size_t i, const Filter *satisfied) {
            for (const auto &f : fs) {
              if (&f == satisfied) continue;
              const int cmp = view.compare_scalar(f.column, i, f.value);
              const bool yes = f.op == "=" ? cmp == 0 : f.op == "<" ? cmp < 0 :
                  f.op == "<=" ? cmp <= 0 : f.op == ">" ? cmp > 0 :
                  f.op == ">=" ? cmp >= 0 : false;
              if (!yes) return false;
            }
            return true;
          };
          exact::Compact::EqualityRange candidates;
          const Filter *indexed_filter = nullptr;
          for (const auto &f : fs) {
            if (f.op == "=" && f.column != pk) {
              auto range = view.equality_range(f.column, f.value);
              if (range.indexed) {
                candidates = range;
                indexed_filter = &f;
                break;
              }
            }
          }
          // A single indexed equality keeps the posting array untouched; any
          // other filter materializes the surviving rows once before scanning.
          std::vector<uint32_t> hits;
          const uint32_t *rows = nullptr;
          size_t row_count = 0;
          if (indexed_filter && fs.size() == 1) {
            rows = candidates.rows;
            row_count = candidates.size;
          } else {
            if (indexed_filter) {
              hits.reserve(candidates.size);
              for (size_t n = 0; n < candidates.size; ++n)
                if (eligible(candidates.rows[n], indexed_filter))
                  hits.push_back(candidates.rows[n]);
            } else {
              hits.reserve(view.count);
              for (size_t i = 0; i < view.count; ++i)
                if (eligible(i, nullptr)) hits.push_back(static_cast<uint32_t>(i));
            }
            rows = hits.data();
            row_count = hits.size();
          }
          run_slices(row_count, [&](size_t begin, size_t end, Heap &heap) {
            scan_list(rows + begin, end - begin, heap);
          });
        }
      } else if (cache_->exact_bypass) {
        // Remember this view's budget bypass until existing invalidation clears it.
        scan_rows(original_visit);
      } else {
        std::vector<Type> types;
        for (const auto &column : schema.columns) types.push_back(column.type);
        exact::Plan plan(std::move(types), projection.col, projection.query.size());
        bool answered = false;
        try {
          // First scan answers this query and computes bounded allocation sizes.
          // The old complete-row cache is absent throughout both build scans.
          store_.scan(st.table, [&](int64_t key, const std::string &data) {
            auto row = unpack_row(data, schema);
            original_visit(key, row);
            plan.observe(row);
          });
          answered = true;
          if (plan.fits()) {
            auto view = std::make_unique<exact::Compact>(plan);
            size_t count = 0;
            store_.scan(st.table, [&](int64_t key, const std::string &data) {
              view->fill(count++, key, unpack_row(data, schema));
            });
            if (count != plan.count)
              throw Error("CORRUPTION", "exact cache row count changed");
            view->prepare_quantized_codes();
            cache_->exact_view = std::move(view); // publish only after full fill
          } else {
            cache_->exact_bypass = true;
          }
        } catch (const std::bad_alloc &) {
          if (!answered) { *cache_ = Cache{}; throw; }
          // Cache allocation is optional; the complete first-scan result remains.
          cache_->exact_bypass = true;
        } catch (...) {
          *cache_ = Cache{};
          throw;
        }
      }
    } else {
      scan_rows(original_visit);
    }
    std::vector<Neighbor> winners;
    while (!nearest.empty()) {
      winners.push_back(nearest.top());
      nearest.pop();
    }
    std::sort(winners.begin(), winners.end(), better_neighbor);
    result.rows.reserve(winners.size());
    for (const auto &n : winners) {
      std::vector<Cell> output;
      output.reserve(ps.size());
      if (winner_view) {
        for (const auto &p : ps) {
          if (p.distance) {
            if (p.col == projection.col && p.query == projection.query)
              output.push_back(n.distance);
            else
              output.push_back(
                  winner_view->distance_cell(n.row, p.col, p.query));
            continue;
          }
          const auto type = schema.columns[p.col].type;
          if (type == Type::BigInt)
            output.push_back(winner_view->integer_cell(n.row, p.col));
          else if (type == Type::Varchar)
            output.push_back(winner_view->text_cell(n.row, p.col));
          else
            output.push_back(winner_view->vector_cell(n.row, p.col));
        }
      } else {
        auto data = store_.get(st.table, n.key);
        if (!data)
          throw Error("CORRUPTION", "missing visible search result");
        auto row = unpack_row(*data, schema);
        for (auto &p : ps)
          output.push_back(project(p, row));
      }
      result.rows.push_back(std::move(output));
    }
    return result;
  }
  struct Candidate {
    int64_t pk;
    std::vector<Cell> output;
    std::vector<Cell> sort;
  };
  auto better = [&](const Candidate &a, const Candidate &b) {
    for (size_t i = 0; i < keys.size(); ++i) {
      int c = compare(a.sort[i], b.sort[i]);
      if (c)
        return keys[i].desc ? c > 0 : c < 0;
    }
    return a.pk < b.pk;
  };
  std::priority_queue<Candidate, std::vector<Candidate>, decltype(better)> heap(
      better);
  std::vector<Candidate> all;
  size_t buffered_bytes = 0;
  std::unique_ptr<SpillSorter> sorter;
  auto weight = [](const Candidate &c) {
    size_t n = sizeof(Candidate) * 2;
    for (auto &v : c.output)
      n += cell_bytes(v);
    for (auto &v : c.sort)
      n += cell_bytes(v);
    return n;
  };
  auto spill = [&](const Candidate &c) {
    std::string key;
    for (size_t i = 0; i < c.sort.size(); ++i)
      ordered_cell(key, c.sort[i], keys[i].desc);
    ordered_u64(key, static_cast<uint64_t>(c.pk) ^ (uint64_t(1) << 63));
    sorter->add(std::move(key), row_json(c.output));
  };
  auto start_spill = [&] {
    sorter = std::make_unique<SpillSorter>(directory_, result_budget);
    while (!heap.empty()) {
      spill(heap.top());
      heap.pop();
    }
    for (auto &c : all)
      spill(c);
    std::vector<Candidate>().swap(all);
    buffered_bytes = 0;
  };
  scan_rows([&](int64_t key, const std::vector<Cell> &row) {
    if (!matches(row, fs))
      return;
    Candidate c;
    c.pk = key;
    for (auto &p : ps)
      c.output.push_back(project(p, row));
    for (auto &k : keys)
      c.sort.push_back(k.projection ? c.output[k.index] : row[k.index]);
    if (sorter) {
      spill(c);
      return;
    }
    const size_t bytes = weight(c);
    if (st.limit) {
      if (heap.size() < *st.limit) {
        if (bytes > result_budget - buffered_bytes) {
          start_spill();
          spill(c);
          return;
        }
        buffered_bytes += bytes;
        heap.push(std::move(c));
      } else if (better(c, heap.top())) {
        buffered_bytes -= weight(heap.top());
        heap.pop();
        if (bytes > result_budget - buffered_bytes) {
          start_spill();
          spill(c);
          return;
        }
        buffered_bytes += bytes;
        heap.push(std::move(c));
      }
    } else {
      if (bytes > result_budget - buffered_bytes) {
        start_spill();
        spill(c);
        return;
      }
      buffered_bytes += bytes;
      all.push_back(std::move(c));
    }
  });
  if (sorter) {
    result.stream = sorter->finish(st.limit);
    return result;
  }
  while (!heap.empty()) {
    all.push_back(heap.top());
    heap.pop();
  }
  std::sort(all.begin(), all.end(), better);
  for (auto &c : all)
    result.rows.push_back(std::move(c.output));
  return result;
}
std::string result_json(const Result &result) {
  std::ostringstream out;
  write_result_json(out, result);
  return out.str();
}
namespace {
void write_query_fields(std::ostream &out, const Result &result) {
  out << "\"columns\":[";
  for (size_t i = 0; i < result.columns.size(); ++i) {
    if (i)
      out << ',';
    out << escaped(result.columns[i]);
  }
  out << "],\"rows\":[";
  bool first = true;
  for (size_t i = 0; i < result.rows.size(); ++i) {
    if (i)
      out << ',';
    out << '[';
    for (size_t j = 0; j < result.rows[i].size(); ++j) {
      if (j)
        out << ',';
      json_cell(out, result.rows[i][j]);
    }
    out << ']';
    first = false;
  }
  if (result.stream) {
    result.stream->reset();
    std::string row;
    while (result.stream->next(row)) {
      if (!first)
        out << ',';
      out << row;
      first = false;
    }
  }
  out << ']';
}
} // namespace
void write_result_json(std::ostream &out, const Result &result) {
  out.imbue(std::locale::classic());
  out << "{\"ok\":true,";
  write_query_fields(out, result);
  out << ",\"affected\":" << result.affected << '}';
}
void write_protocol_result_json(std::ostream &out, const Result &result,
                                const std::string &id_json) {
  out.imbue(std::locale::classic());
  out << "{\"id\":" << id_json << ",\"ok\":true";
  if (!result.columns.empty()) {
    out << ',';
    write_query_fields(out, result);
  } else if (result.reports_affected)
    out << ",\"affected_rows\":" << result.affected;
  out << '}';
}
std::string protocol_error_json(const std::string &id_json,
                                const std::string &code,
                                const std::string &message) {
  return "{\"id\":" + id_json + ",\"ok\":false,\"error\":{\"code\":" +
         escaped(code) + ",\"message\":" + escaped(message) + "}}";
}
std::string error_json(const std::string &code, const std::string &message) {
  return "{\"ok\":false,\"code\":" + escaped(code) +
         ",\"error\":" + escaped(message) + "}";
}
} // namespace mvdb
