#include "engine.hpp"
#include "spill.hpp"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <limits>
#include <locale>
#include <queue>
#include <set>
#include <sstream>

namespace mvdb {
namespace {
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
      auto token = s.substr(start, p - start);
      char *end = nullptr;
      float f = std::strtof(token.c_str(), &end);
      if (end != token.c_str() + token.size() || !std::isfinite(f))
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
  bool complete = false;
  size_t bytes = 0;
  static constexpr size_t budget = 12 * 1024 * 1024;
  struct Columnar {
    size_t count = 0, dim = 0, vector_col = 0, filter_col = 0;
    Type filter_type = Type::BigInt;
    std::unique_ptr<int64_t[]> ids;
    std::unique_ptr<float[]> vectors;
    std::unique_ptr<int64_t[]> integers;
    std::unique_ptr<size_t[]> offsets;
    std::unique_ptr<char[]> strings;
  };
  std::unique_ptr<Columnar> columnar;
  bool columnar_rejected = false;
};
Engine::Engine(const std::string &directory)
    : store_(directory), directory_(directory),
      cache_(std::make_unique<Cache>()) {}
Engine::~Engine() = default;

Result Engine::execute(const std::string &sql) {
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
    return execute_statement(st);
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
    };
    auto better_neighbor = [](const Neighbor &a, const Neighbor &b) {
      return a.distance < b.distance ||
             (a.distance == b.distance && a.key < b.key);
    };
    std::priority_queue<Neighbor, std::vector<Neighbor>,
                        decltype(better_neighbor)>
        nearest(better_neighbor);
    const auto &projection = ps[keys[0].index];
    auto accept_neighbor = [&](int64_t key, double distance) {
      Neighbor n{distance, key};
      if (nearest.size() < *st.limit)
        nearest.push(n);
      else if (better_neighbor(n, nearest.top())) {
        nearest.pop();
        nearest.push(n);
      }
    };
    // The experimental layout supports one scalar filter column. Other
    // schemas and predicates continue through the generic row scanner.
    size_t scalar = schema.columns.size(), scalar_count = 0;
    for (size_t i = 0; i < schema.columns.size(); ++i)
      if (i != pk && schema.columns[i].type != Type::Vector) {
        scalar = i;
        ++scalar_count;
      }
    const bool eligible = scalar_count == 1 && fs.size() <= 1 &&
        (fs.empty() || (fs[0].column == scalar && fs[0].op == "="));
    if (eligible && (cache_->table != st.table ||
                     (!cache_->columnar && !cache_->columnar_rejected))) {
      *cache_ = Cache{};
      cache_->table = st.table;
      const size_t dim = schema.columns[projection.col].size;
      const bool strings = schema.columns[scalar].type == Type::Varchar;
      // Reserve slack for allocation headers and the transient decoded row.
      constexpr size_t usable = Cache::budget - 65536;
      size_t count = 0, text_bytes = 0;
      bool fits = dim <= usable / sizeof(float);
      try {
        store_.scan(st.table, [&](int64_t, const std::string &data) {
          if (!fits) return;
          auto row = unpack_row(data, schema);
          const size_t width = sizeof(int64_t) + dim * sizeof(float) +
              (strings ? sizeof(size_t) : sizeof(int64_t));
          if (count >= usable / width) { fits = false; return; }
          ++count;
          if (strings) {
            const auto length = std::get<std::string>(row[scalar]).size();
            if (length > usable - text_bytes) { fits = false; return; }
            text_bytes += length;
          }
          if (count * width > usable - text_bytes ||
              (strings && sizeof(size_t) > usable - text_bytes - count * width))
            fits = false;
        });
        if (fits) {
          auto column = std::make_unique<Cache::Columnar>();
          column->count = count; column->dim = dim;
          column->vector_col = projection.col; column->filter_col = scalar;
          column->filter_type = schema.columns[scalar].type;
          column->ids = std::make_unique<int64_t[]>(count);
          column->vectors = std::make_unique<float[]>(count * dim);
          if (strings) {
            column->offsets = std::make_unique<size_t[]>(count + 1);
            column->strings = std::make_unique<char[]>(text_bytes);
          } else column->integers = std::make_unique<int64_t[]>(count);
          size_t row_index = 0, offset = 0;
          store_.scan(st.table, [&](int64_t key, const std::string &data) {
            auto row = unpack_row(data, schema);
            column->ids[row_index] = key;
            const auto &v = std::get<std::vector<float>>(row[projection.col]);
            std::copy(v.begin(), v.end(), column->vectors.get() + row_index * dim);
            if (strings) {
              const auto &value = std::get<std::string>(row[scalar]);
              column->offsets[row_index] = offset;
              std::copy(value.begin(), value.end(), column->strings.get() + offset);
              offset += value.size();
            } else column->integers[row_index] = std::get<int64_t>(row[scalar]);
            ++row_index;
          });
          if (strings) column->offsets[count] = offset;
          cache_->columnar = std::move(column);
        } else cache_->columnar_rejected = true;
      } catch (...) { *cache_ = Cache{}; throw; }
    }
    const auto *column = eligible && cache_->table == st.table ? cache_->columnar.get() : nullptr;
    if (column && column->vector_col == projection.col && column->filter_col == scalar) {
      for (size_t i = 0; i < column->count; ++i) {
        if (!fs.empty()) {
          if (column->filter_type == Type::BigInt) {
            if (column->integers[i] != std::get<int64_t>(fs[0].value)) continue;
          } else {
            const auto &value = std::get<std::string>(fs[0].value);
            const size_t begin = column->offsets[i], length = column->offsets[i + 1] - begin;
            if (length != value.size() || std::memcmp(column->strings.get() + begin, value.data(), length) != 0) continue;
          }
        }
        double sum = 0;
        for (size_t j = 0; j < column->dim; ++j) {
          double d = double(column->vectors[i * column->dim + j]) - double(projection.query[j]);
          sum += d * d;
        }
        accept_neighbor(column->ids[i], std::sqrt(sum));
      }
    } else scan_rows([&](int64_t key, const std::vector<Cell> &row) {
      if (!matches(row, fs))
        return;
      accept_neighbor(key, std::get<double>(project(projection, row)));
    });
    std::vector<Neighbor> winners;
    while (!nearest.empty()) {
      winners.push_back(nearest.top());
      nearest.pop();
    }
    std::sort(winners.begin(), winners.end(), better_neighbor);
    for (const auto &n : winners) {
      auto data = store_.get(st.table, n.key);
      if (!data)
        throw Error("CORRUPTION", "missing visible search result");
      auto row = unpack_row(*data, schema);
      std::vector<Cell> output;
      for (auto &p : ps)
        output.push_back(project(p, row));
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
void write_result_json(std::ostream &out, const Result &result) {
  out.imbue(std::locale::classic());
  out << "{\"ok\":true,\"columns\":[";
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
  out << "],\"affected\":" << result.affected << '}';
}
std::string error_json(const std::string &code, const std::string &message) {
  return "{\"ok\":false,\"code\":" + escaped(code) +
         ",\"error\":" + escaped(message) + "}";
}
} // namespace mvdb
