#pragma once
// Direct row encoding for INSERT: turn parsed literals into the journal row
// bytes in one pass, with no intermediate Cell/vector<float> materialization.
// The produced bytes are identical to pack_row(convert(...)) for the same input.
#include "sql.hpp"
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace mvdb::codec {
// Unicode scalar count for a validated UTF-8 string.
inline size_t utf8_count(const std::string &s) {
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
// One left-to-right scan of a quoted VECTOR literal. Every component is handed
// to the sink as float32; the scanner itself is the historical one, including
// the strtof fallback for finite FP32 underflow and signed zero.
template <class Sink>
void parse_vector_body(std::string_view body, uint32_t dim, Sink &&emit) {
  const std::string_view s = body;
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
  size_t count = 0;
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
        const std::string token(s.substr(start, p - start));
        char *end = nullptr;
        f = std::strtof(token.c_str(), &end);
        if (end != token.c_str() + token.size())
          throw Error("TYPE", "vector component overflows finite float32");
      }
      if (!std::isfinite(f))
        throw Error("TYPE", "vector component overflows finite float32");
      emit(f);
      if (++count > dim)
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
  if (p != s.size() || count != dim)
    throw Error("TYPE", "vector dimension mismatch or trailing input");
}
template <class Sink>
void parse_vector_text(const Literal &l, uint32_t dim, Sink &&emit) {
  if (!l.quoted)
    throw Error("TYPE", "VECTOR requires a quoted array");
  parse_vector_body(l.text, dim, std::forward<Sink>(emit));
}
inline std::vector<float> vector_literal_text(const Literal &l, uint32_t dim) {
  std::vector<float> v;
  parse_vector_text(l, dim, [&](float f) { v.push_back(f); });
  return v;
}
inline void put_u32(std::string &out, uint32_t x) {
  for (int i = 0; i < 4; ++i) out.push_back(char(x >> (8 * i)));
}
inline void put_u64(std::string &out, uint64_t x) {
  for (int i = 0; i < 8; ++i) out.push_back(char(x >> (8 * i)));
}
// Encoding plan: the schema columns in storage order plus the primary key slot.
struct Plan {
  std::vector<Column> columns;
  size_t primary = 0;
};
inline Plan make_plan(std::vector<Column> columns, size_t primary) {
  return Plan{std::move(columns), primary};
}
inline int64_t parse_bigint(const Literal &l) {
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
inline void encode_vector_body(std::string_view body, uint32_t dim,
                               std::string &out) {
  parse_vector_body(body, dim, [&](float f) {
    uint32_t bits;
    std::memcpy(&bits, &f, 4);
    put_u32(out, bits);
  });
}
inline void encode_vector(const Literal &l, uint32_t dim, std::string &out) {
  parse_vector_text(l, dim, [&](float f) {
    uint32_t bits;
    std::memcpy(&bits, &f, 4);
    put_u32(out, bits);
  });
}
// Append tuple bytes in storage column order and return the primary key value.
// `source[column]` is the tuple slot holding that column, so an INSERT list in a
// different order still writes the canonical row layout.
inline int64_t parse_bigint_text(std::string_view text) {
  int64_t x = 0;
  const char *begin = text.data();
  const char *end = begin + text.size();
  if (begin != end && *begin == '+') ++begin;
  auto res = std::from_chars(begin, end, x);
  if (begin == end || res.ec != std::errc() || res.ptr != end)
    throw Error("TYPE", "invalid or overflowing BIGINT");
  return x;
}
inline const char *skip_spaces(const char *p, const char *end) {
  while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) ++p;
  return p;
}
// Encode one tuple written as raw SQL text (the part between its parentheses).
// Returns false for anything outside the supported fast-path grammar so the
// caller can fall back to the general parser; never applies partial work.
inline bool encode_tuple_text(std::string_view tuple, const Plan &plan,
                              std::string &out, int64_t &key) {
  const char *p = tuple.data();
  const char *end = p + tuple.size();
  for (size_t column = 0; column < plan.columns.size(); ++column) {
    const Column &c = plan.columns[column];
    p = skip_spaces(p, end);
    if (p >= end) return false;
    if (*p == '\'') {
      const char *start = ++p;
      bool escaped = false;
      while (p < end) {
        if (*p == '\'') {
          if (p + 1 < end && p[1] == '\'') { escaped = true; p += 2; continue; }
          break;
        }
        ++p;
      }
      if (p >= end) return false;
      const std::string_view body(start, static_cast<size_t>(p - start));
      ++p;
      // Backslash escapes follow the general tokenizer's rules; leave those
      // statements to it rather than duplicating the mapping here.
      if (body.find('\\') != std::string_view::npos) return false;
      if (c.type == Type::Varchar) {
        std::string value;
        value.reserve(body.size());
        for (size_t i = 0; i < body.size(); ++i) {
          if (body[i] == '\'' && i + 1 < body.size() && body[i + 1] == '\'') ++i;
          value.push_back(body[i]);
        }
        if (utf8_count(value) > c.size)
          throw Error("TYPE", "VARCHAR character limit exceeded");
        if (value.size() > UINT32_MAX)
          throw Error("RESOURCE", "value exceeds serialization limit");
        put_u32(out, static_cast<uint32_t>(value.size()));
        out.append(value);
      } else if (c.type == Type::Vector) {
        if (escaped) return false;
        encode_vector_body(body, c.size, out);
      } else {
        return false;
      }
    } else {
      const char *start = p;
      while (p < end && *p != ',') ++p;
      const char *stop = p;
      while (stop > start && (stop[-1] == ' ' || stop[-1] == '\t')) --stop;
      if (c.type != Type::BigInt) return false;
      const int64_t value =
          parse_bigint_text(std::string_view(start, static_cast<size_t>(stop - start)));
      put_u64(out, static_cast<uint64_t>(value));
      if (column == plan.primary) key = value;
    }
    p = skip_spaces(p, end);
    if (column + 1 < plan.columns.size()) {
      if (p >= end || *p != ',') return false;
      ++p;
    }
  }
  p = skip_spaces(p, end);
  return p == end;
}
inline int64_t encode_row(const std::vector<Literal> &tuple,
                          const std::vector<size_t> &source, const Plan &plan,
                          std::string &out) {
  int64_t key = 0;
  for (size_t column = 0; column < plan.columns.size(); ++column) {
    const size_t slot = source[column];
    if (slot == SIZE_MAX)
      throw Error("TYPE", "column/value count mismatch");
    const Column &c = plan.columns[column];
    const Literal &literal = tuple[slot];
    if (c.type == Type::BigInt) {
      const int64_t value = parse_bigint(literal);
      if (column == plan.primary) key = value;
      put_u64(out, static_cast<uint64_t>(value));
    } else if (c.type == Type::Varchar) {
      if (!literal.quoted)
        throw Error("TYPE", "VARCHAR requires a string");
      if (utf8_count(literal.text) > c.size)
        throw Error("TYPE", "VARCHAR character limit exceeded");
      if (literal.text.size() > UINT32_MAX)
        throw Error("RESOURCE", "value exceeds serialization limit");
      put_u32(out, static_cast<uint32_t>(literal.text.size()));
      out.append(literal.text);
    } else {
      encode_vector(literal, c.size, out);
    }
  }
  return key;
}
} // namespace mvdb::codec
