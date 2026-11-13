#include "row_codec.hpp"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool ok, const std::string &what) {
  if (!ok) throw std::runtime_error("row codec check failed: " + what);
}
std::string u32(uint32_t x) {
  std::string out;
  for (int i = 0; i < 4; ++i) out.push_back(char(x >> (8 * i)));
  return out;
}
std::string u64(uint64_t x) {
  std::string out;
  for (int i = 0; i < 8; ++i) out.push_back(char(x >> (8 * i)));
  return out;
}
std::string f32(float value) {
  uint32_t bits;
  std::memcpy(&bits, &value, 4);
  return u32(bits);
}
mvdb::Literal text(std::string value, bool quoted = true) {
  mvdb::Literal literal;
  literal.text = std::move(value);
  literal.quoted = quoted;
  return literal;
}
void expect_error(const std::vector<mvdb::Literal> &tuple,
                  const std::vector<size_t> &mapping,
                  const mvdb::codec::Plan &plan, const std::string &code) {
  std::string out;
  try {
    mvdb::codec::encode_row(tuple, mapping, plan, out);
  } catch (const mvdb::Error &error) {
    require(error.code == code, "wrong error code for " + code + ": " + error.code);
    return;
  }
  throw std::runtime_error("expected error " + code);
}
} // namespace

int main() {
  using namespace mvdb;
  // id BIGINT PRIMARY KEY, tag VARCHAR(8), v VECTOR(3)
  codec::Plan plan{std::vector<Column>{Column{"id", Type::BigInt, 0, true},
                                       Column{"tag", Type::Varchar, 8, false},
                                       Column{"v", Type::Vector, 3, false}},
                   0};
  const std::vector<size_t> mapping{0, 1, 2};  // storage column -> tuple slot
  std::string out;
  const int64_t key = codec::encode_row(
      {text("42", false), text("ok"), text("[1,2.5,-3.25]")}, mapping, plan, out);
  require(key == 42, "primary key value");
  require(out == u64(42) + u32(2) + "ok" + f32(1.0f) + f32(2.5f) + f32(-3.25f),
          "encoded row bytes");
  out.clear();
  // Column mapping order is honoured: encode (id, v, tag) into storage order.
  // tuple slot 1 holds v (column 2) and slot 2 holds tag (column 1).
  const std::vector<size_t> reordered{0, 2, 1};
  codec::encode_row({text("7", false), text("[0.5,0.25,0]"), text("x")},
                    reordered, plan, out);
  require(out == u64(7) + u32(1) + "x" + f32(0.5f) + f32(0.25f) + f32(0.0f),
          "mapped row bytes");

  // Buffer reuse: a second encode appends to a cleared buffer, not to stale bytes.
  std::string reused;
  codec::encode_row({text("1", false), text("a"), text("[0,0,0]")}, mapping,
                    plan, reused);
  reused.clear();
  codec::encode_row({text("2", false), text("ab"), text("[1,1,1]")}, mapping,
                    plan, reused);
  require(reused == u64(2) + u32(2) + "ab" + f32(1.0f) + f32(1.0f) + f32(1.0f),
          "buffer reuse");

  // Unicode counts as one character per scalar value.
  std::string unicode;
  codec::encode_row({text("1", false), text("中文🙂"), text("[1,2,3]")}, mapping,
                    plan, unicode);
  require(unicode == u64(1) + u32(10) + "中文🙂" + f32(1.0f) + f32(2.0f) +
                        f32(3.0f),
          "utf-8 payload");

  expect_error({text("'1'"), text("a"), text("[1,2,3]")}, mapping, plan, "TYPE");
  expect_error({text("1", false), text("123456789"), text("[1,2,3]")}, mapping,
               plan, "TYPE");
  expect_error({text("1", false), text("a"), text("[1,2]")}, mapping, plan,
               "TYPE");
  expect_error({text("1", false), text("a"), text("[1,2,3,4]")}, mapping, plan,
               "TYPE");
  expect_error({text("1", false), text("a"), text("[1,2,-]")}, mapping, plan,
               "TYPE");
  expect_error({text("99999999999999999999", false), text("a"), text("[1,2,3]")},
               mapping, plan, "TYPE");
  std::cout << "direct row encoding matches the reference bytes\n";
  return 0;
}
