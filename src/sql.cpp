#include "sql.hpp"

#include <limits>
#include <set>
#include <string_view>

namespace mvdb {
namespace {
enum class TokenKind { Word, Identifier, Number, String, Symbol, End };
struct Token { TokenKind kind; std::string text; size_t offset; };

bool digit(char c) { return c >= '0' && c <= '9'; }
bool alpha(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
std::string lower(std::string value) {
  for (char& c : value) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  return value;
}
bool space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f'; }
[[noreturn]] void syntax(size_t offset, const std::string& reason) {
  throw Error("SYNTAX", reason + " at byte " + std::to_string(offset));
}

std::vector<Token> tokenize(const std::string& sql) {
  std::vector<Token> tokens;
  size_t i = 0;
  while (i < sql.size()) {
    const char c = sql[i];
    if (space(c)) { ++i; continue; }
    if (c == '#' || (c == '-' && i + 1 < sql.size() && sql[i + 1] == '-')) {
      while (i < sql.size() && sql[i] != '\n') ++i;
      continue;
    }
    if (c == '/' && i + 1 < sql.size() && sql[i + 1] == '*') {
      const size_t start = i;
      i += 2;
      // MySQL executable comments must not be silently ignored.
      if (i < sql.size() && (sql[i] == '!' || sql[i] == '+'))
        syntax(start, "Executable comments and hints are unsupported");
      while (i + 1 < sql.size() && !(sql[i] == '*' && sql[i + 1] == '/')) ++i;
      if (i + 1 == sql.size()) syntax(start, "Unterminated comment");
      if (i >= sql.size()) syntax(start, "Unterminated comment");
      i += 2;
      continue;
    }
    const size_t start = i;
    if (c == '\'' || c == '"' || c == '`') {
      ++i;
      std::string value;
      bool closed = false;
      while (i < sql.size()) {
        const char next = sql[i++];
        if (next == c) {
          if (i < sql.size() && sql[i] == c) { value += c; ++i; }
          else { closed = true; break; }
        } else if (next == '\\' && c != '`') {
          if (i == sql.size()) syntax(start, "Unterminated escape");
          switch (sql[i++]) {
            case '0': value += '\0'; break;
            case 'b': value += '\b'; break;
            case 'n': value += '\n'; break;
            case 'r': value += '\r'; break;
            case 't': value += '\t'; break;
            case 'Z': value += '\x1a'; break;
            default: value += sql[i - 1]; break;
          }
        } else { value += next; }
      }
      if (!closed) syntax(start, "Unterminated quoted value");
      if (c == '`') {
        if (value.empty()) syntax(start, "Empty identifier");
        tokens.push_back({TokenKind::Identifier, lower(std::move(value)), start});
      } else tokens.push_back({TokenKind::String, std::move(value), start});
      continue;
    }
    if (alpha(c) || c == '_') {
      ++i;
      while (i < sql.size() && (alpha(sql[i]) || digit(sql[i]) || sql[i] == '_' || sql[i] == '$')) ++i;
      tokens.push_back({TokenKind::Word, lower(sql.substr(start, i - start)), start});
      continue;
    }
    if (digit(c) || c == '.' || c == '+' || c == '-') {
      if (c == '+' || c == '-') ++i;
      bool any = false;
      while (i < sql.size() && digit(sql[i])) { ++i; any = true; }
      if (i < sql.size() && sql[i] == '.') {
        ++i;
        while (i < sql.size() && digit(sql[i])) { ++i; any = true; }
      }
      if (!any) syntax(start, "Expected numeric literal");
      if (i < sql.size() && (sql[i] == 'e' || sql[i] == 'E')) {
        ++i;
        if (i < sql.size() && (sql[i] == '+' || sql[i] == '-')) ++i;
        const size_t exponent = i;
        while (i < sql.size() && digit(sql[i])) ++i;
        if (i == exponent) syntax(start, "Invalid numeric exponent");
      }
      if (i < sql.size() && (alpha(sql[i]) || sql[i] == '_' || sql[i] == '.'))
        syntax(start, "Invalid numeric literal");
      tokens.push_back({TokenKind::Number, sql.substr(start, i - start), start});
      continue;
    }
    if (std::string_view("(),;*=<>").find(c) != std::string_view::npos) {
      ++i;
      if ((c == '<' || c == '>') && i < sql.size() && sql[i] == '=') ++i;
      else if (c == '<' && i < sql.size() && sql[i] == '>')
        syntax(start, "Not-equal comparison is unsupported");
      tokens.push_back({TokenKind::Symbol, sql.substr(start, i - start), start});
      continue;
    }
    syntax(start, "Unexpected character");
  }
  tokens.push_back({TokenKind::End, "", sql.size()});
  return tokens;
}

bool reserved(const std::string& word) {
  static const std::set<std::string> words = {
    "select", "from", "where", "order", "by", "limit", "asc", "desc", "as", "and", "or",
    "insert", "into", "values", "update", "set", "delete", "create", "table", "vector", "index",
    "on", "primary", "key", "bigint", "varchar", "begin", "commit", "rollback", "null", "true",
    "false", "join", "inner", "left", "right", "outer", "group", "having", "union", "offset",
    "distinct", "not", "default", "alter", "drop", "is", "in", "like", "between", "exists"
  };
  return words.find(word) != words.end();
}

class Parser {
 public:
  explicit Parser(const std::string& sql) : tokens_(tokenize(sql)) {}
  Statement parse() {
    Statement s;
    if (accept("create")) create(s);
    else if (accept("insert")) insert(s);
    else if (accept("select")) select(s);
    else if (accept("update")) update(s);
    else if (accept("delete")) remove(s);
    else if (accept("begin")) s.kind = Statement::Begin;
    else if (accept("commit")) s.kind = Statement::Commit;
    else if (accept("rollback")) s.kind = Statement::Rollback;
    else syntax(current().offset, "Expected a supported SQL statement");
    accept(";");
    if (current().kind != TokenKind::End) syntax(current().offset, "Unexpected trailing input");
    return s;
  }
 private:
  std::vector<Token> tokens_;
  size_t pos_ = 0;
  const Token& current() const { return tokens_[pos_]; }
  bool is(const std::string& value) const {
    return (current().kind == TokenKind::Word || current().kind == TokenKind::Symbol)
      && current().text == value;
  }
  bool accept(const std::string& value) { if (!is(value)) return false; ++pos_; return true; }
  void expect(const std::string& value) {
    if (!accept(value)) syntax(current().offset, "Expected '" + value + "'");
  }
  std::string identifier() {
    const Token& t = current();
    if (t.kind != TokenKind::Identifier && (t.kind != TokenKind::Word || reserved(t.text)))
      syntax(t.offset, "Expected identifier");
    ++pos_;
    return t.text;
  }
  uint64_t uint_literal() {
    const Token& t = current();
    if (t.kind != TokenKind::Number || t.text.empty()) syntax(t.offset, "Expected unsigned integer");
    uint64_t n = 0;
    for (char c : t.text) {
      if (!digit(c)) syntax(t.offset, "Expected unsigned integer");
      const unsigned d = static_cast<unsigned>(c - '0');
      if (n > (std::numeric_limits<uint64_t>::max() - d) / 10)
        syntax(t.offset, "Integer exceeds uint64 range");
      n = n * 10 + d;
    }
    ++pos_;
    return n;
  }
  Literal literal() {
    const Token& t = current();
    if (t.kind != TokenKind::String && t.kind != TokenKind::Number)
      syntax(t.offset, "Expected string or numeric literal");
    ++pos_;
    return {t.text, t.kind == TokenKind::String};
  }
  void create(Statement& s) {
    if (accept("vector")) {
      s.kind = Statement::CreateIndex;
      expect("index"); s.index_name = identifier(); expect("on"); s.table = identifier();
      expect("("); s.index_column = identifier(); expect(")");
      return;
    }
    s.kind = Statement::CreateTable;
    expect("table"); s.table = identifier(); expect("(");
    std::vector<std::string> table_primary;
    do {
      if (accept("primary")) {
        expect("key"); expect("("); table_primary.push_back(identifier()); expect(")");
      } else {
        Column c;
        c.name = identifier();
        if (accept("bigint")) c.type = Type::BigInt;
        else {
          if (accept("varchar")) c.type = Type::Varchar;
          else if (accept("vector")) c.type = Type::Vector;
          else syntax(current().offset, "Expected BIGINT, VARCHAR, or VECTOR");
          expect("(");
          const uint64_t size = uint_literal();
          if (size == 0 || size > std::numeric_limits<uint32_t>::max())
            syntax(current().offset, "Type length must be between 1 and UINT32_MAX");
          c.size = static_cast<uint32_t>(size);
          expect(")");
        }
        if (accept("primary")) { expect("key"); c.primary = true; }
        s.schema.push_back(std::move(c));
      }
    } while (accept(","));
    expect(")");
    if (s.schema.empty()) syntax(current().offset, "Table requires columns");
    if (table_primary.size() > 1) syntax(current().offset, "Multiple primary-key constraints");
    if (!table_primary.empty()) {
      bool found = false;
      for (auto& c : s.schema) {
        if (c.primary) syntax(current().offset, "Multiple primary-key constraints");
        if (c.name == table_primary[0]) { c.primary = true; found = true; }
      }
      if (!found) syntax(current().offset, "Primary key references unknown column");
    }
  }
  void insert(Statement& s) {
    s.kind = Statement::Insert;
    expect("into"); s.table = identifier();
    if (accept("(")) {
      do { s.insert_columns.push_back(identifier()); } while (accept(","));
      expect(")");
    }
    expect("values");
    do {
      expect("(");
      std::vector<Literal> row;
      do { row.push_back(literal()); } while (accept(","));
      expect(")");
      s.values.push_back(std::move(row));
    } while (accept(","));
  }
  Expr expression() {
    Expr e;
    if (accept("*")) e.kind = Expr::Star;
    else if (accept("l2_distance")) {
      e.kind = Expr::Distance;
      expect("("); e.column = identifier(); expect(","); e.vector = literal(); expect(")");
    } else { e.kind = Expr::ColumnRef; e.column = identifier(); }
    if (accept("as")) {
      if (e.kind == Expr::Star) syntax(current().offset, "Star projection cannot have an alias");
      e.alias = identifier();
    }
    return e;
  }
  void conditions(std::vector<Condition>& out) {
    do {
      if (accept("(")) { conditions(out); expect(")"); }
      else {
        Condition c;
        c.column = identifier();
        if (!(is("=") || is("<") || is("<=") || is(">") || is(">=")))
          syntax(current().offset, "Expected supported comparison operator");
        c.op = current().text; ++pos_;
        c.value = literal(); out.push_back(std::move(c));
      }
    } while (accept("and"));
  }
  void where(Statement& s) { if (accept("where")) conditions(s.conditions); }
  void select(Statement& s) {
    s.kind = Statement::Select;
    do { s.projections.push_back(expression()); } while (accept(","));
    expect("from"); s.table = identifier(); where(s);
    if (accept("order")) {
      expect("by");
      do {
        Order o; o.name = identifier();
        if (accept("desc")) o.descending = true; else accept("asc");
        s.order.push_back(std::move(o));
      } while (accept(","));
    }
    if (accept("limit")) s.limit = uint_literal();
  }
  void update(Statement& s) {
    s.kind = Statement::Update; s.table = identifier(); expect("set");
    do {
      auto name = identifier(); expect("="); auto value = literal();
      s.assignments.emplace_back(std::move(name), std::move(value));
    } while (accept(","));
    where(s);
  }
  void remove(Statement& s) {
    s.kind = Statement::Delete; expect("from"); s.table = identifier(); where(s);
  }
};
}
Statement parse_sql(const std::string& sql) { return Parser(sql).parse(); }
}
