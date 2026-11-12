#include "protocol.hpp"
#include <chrono>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace {
int checks = 0;
void check(bool ok, const char *message) {
  ++checks;
  if (!ok) throw std::runtime_error(message);
}
mvdb::Request parse(const std::string &line) {
  mvdb::Request request;
  mvdb::parse_request(line, request);
  return request;
}
void rejected(const std::string &line) {
  try { parse(line); }
  catch (const mvdb::Error &e) {
    check(!e.code.empty(), "missing error code");
    return;
  }
  throw std::runtime_error("accepted invalid request: " + line);
}
}
int main() {
  namespace fs = std::filesystem;
  auto directory = fs::temp_directory_path() / ("mvdb-protocol-" +
      std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  try {
    for (const std::string id : {
         "0", "-0", "9223372036854775807", "-9223372036854775808",
         "18446744073709551616", "123456789012345678901234567890",
         "1.0", "-0.0", "1e3", "null", "true", "false",
         R"("id-\u4e2d-\ud83d\ude42")", R"([1,"a",null,{"x":1.0}])",
         R"({"nested":[false,{"x":12345678901234567890}]})"}) {
      auto request = parse("{\"id\":" + id + ",\"op\":\"shutdown\"}");
      check(request.id_json == id, "id token changed");
      check(request.op == mvdb::Request::Op::Shutdown, "wrong shutdown operation");
    }
    auto r = parse(R"({"sql":"SELECT\nid FROM t WHERE s=';\"\\\b\f\r\t\u0000\u4e2d\ud83d\ude42';","op":"execute","id":"x","search_mode":"ann"})");
    check(r.sql == std::string("SELECT\nid FROM t WHERE s=';\"\\\b\f\r\t") +
                   '\0' + u8"中🙂';", "Unicode/escape decoding");
    check(r.search_mode == mvdb::SearchMode::Ann, "ann was not forwarded");
    for(size_t n=0;n<70;++n) {
      const std::string prefix(n,'a');
      const std::string head="{\"id\":1,\"op\":\"execute\",\"sql\":\""+prefix;
      check(parse(head+"\\n\\\"\\\\\\u4e2d\"}").sql==prefix+"\n\"\\"+u8"中", "string boundary escapes");
      check(parse(head+u8"中🙂\"}").sql==prefix+u8"中🙂", "string boundary UTF-8");
      check(parse(head+std::string(1,char(0x7f))+"\"}").sql==prefix+char(0x7f), "DEL is valid JSON text");
      rejected(head+char(0x1f)+"\"}");
      rejected(head+char(0x80)+"\"}");
      rejected(head+"\\q\"}");
      rejected(head);
    }
    check(parse(R"({"id":1,"op":"execute","sql":"SELECT id FROM t"})").search_mode
          == mvdb::SearchMode::Exact, "default exact");
    check(parse(R"({"id":1,"op":"execute","sql":"","search_mode":"exact"})").search_mode
          == mvdb::SearchMode::Exact, "explicit exact");
    check(parse(u8"{\"id\":\"中文🙂\",\"op\":\"shutdown\"}").id_json == u8"\"中文🙂\"", "UTF-8 identity");
    check(parse(R"({"unknown":{"valid":[null,true,2]},"id":1,"op":"shutdown"})").id_json == "1", "unknown fields");
    for (const std::string bad : {
         "", "[]", "null", "{}",
         R"({"op":"shutdown"})", R"({"id":1})",
         R"({"id":1,"op":true})", R"({"id":1,"op":"execute"})",
         R"({"id":1,"op":"execute","sql":null})",
         R"({"id":1,"op":"execute","sql":"","search_mode":true})",
         R"({"id":1,"op":"execute","sql":"","search_mode":"approx"})",
         R"({"id":1,"op":"unsupported"})",
         R"({"id":1,"id":2,"op":"shutdown"})",
         R"({"id":1,"\u0069d":2,"op":"shutdown"})",
         R"({"id":{"x":1,"x":2},"op":"shutdown"})",
         R"({"id":01,"op":"shutdown"})", R"({"id":+1,"op":"shutdown"})",
         R"({"id":.5,"op":"shutdown"})", R"({"id":1.,"op":"shutdown"})",
         R"({"id":1e,"op":"shutdown"})", R"({"id":NaN,"op":"shutdown"})",
         R"({"id":Infinity,"op":"shutdown"})",
         R"({"id":[1,],"op":"shutdown"})", R"({"id":1,"op":"shutdown",})",
         R"({"id":"\ud800","op":"shutdown"})",
         R"({"id":"\udc00","op":"shutdown"})",
         R"({"id":"\ud800\u0041","op":"shutdown"})",
         R"({"id":"\uZZZZ","op":"shutdown"})",
         R"({"id":"\q","op":"shutdown"})",
         "{\"id\":\"raw\nnewline\",\"op\":\"shutdown\"}",
         R"({"id":1,"op":"shutdown"} false)"})
      rejected(bad);
    for (const auto &invalid_utf8 : {std::string("\xc0\xaf", 2),
        std::string("\xed\xa0\x80", 3), std::string("\xf4\x90\x80\x80", 4),
        std::string("\xe2\x82", 2), std::string("\x80", 1)})
      rejected("{\"id\":\"" + invalid_utf8 + "\",\"op\":\"shutdown\"}");
    rejected("{\"id\":" + std::string(130, '[') + "0" + std::string(130, ']') + ",\"op\":\"shutdown\"}");
    mvdb::Request invalid;
    try { mvdb::parse_request(R"({"id":1.0,"op":"bad"})", invalid); }
    catch (const mvdb::Error &) {}
    check(invalid.id_json == "1.0", "valid id lost on semantic request error");
    {
      mvdb::Engine db(directory.string());
      auto ddl = db.execute("CREATE TABLE t(id BIGINT PRIMARY KEY,s VARCHAR(32),v VECTOR(2))");
      std::ostringstream ddl_out;
      mvdb::write_protocol_result_json(ddl_out, ddl, "1.0");
      check(ddl_out.str() == "{\"id\":1.0,\"ok\":true}", "DDL response");
      auto inserted = db.execute("INSERT INTO t VALUES (9223372036854775807,'hello','[1,2]')");
      std::ostringstream inserted_out;
      mvdb::write_protocol_result_json(inserted_out, inserted, "\"insert\"");
      check(inserted_out.str() == "{\"id\":\"insert\",\"ok\":true,\"affected_rows\":1}", "affected_rows");
      auto selected = db.execute("SELECT id FROM t", mvdb::SearchMode::Ann);
      std::ostringstream selected_out;
      mvdb::write_protocol_result_json(selected_out, selected, "18446744073709551616");
      check(selected_out.str() == "{\"id\":18446744073709551616,\"ok\":true,\"columns\":[\"id\"],\"rows\":[[9223372036854775807]]}", "BIGINT response");
      auto empty = db.execute("SELECT s FROM t WHERE id=0");
      std::ostringstream empty_out;
      mvdb::write_protocol_result_json(empty_out, empty, "1");
      check(empty_out.str() == "{\"id\":1,\"ok\":true,\"columns\":[\"s\"],\"rows\":[]}", "empty projection columns");
      db.execute("BEGIN");
      db.execute("INSERT INTO t VALUES (2,'rollback','[0,0]')");
      db.prepare_shutdown();
      // Locks must already be released even while the closed Engine exists.
      mvdb::Engine reopened(directory.string());
      auto kept = reopened.execute("SELECT id FROM t");
      check(kept.rows.size() == 1 && std::get<int64_t>(kept.rows[0][0]) == INT64_MAX, "shutdown rollback and recovery");
      reopened.prepare_shutdown();
    }
    check(mvdb::protocol_error_json("\"id\"", "TYPE", "bad\n\"value\"") ==
          "{\"id\":\"id\",\"ok\":false,\"error\":{\"code\":\"TYPE\",\"message\":\"bad\\u000a\\\"value\\\"\"}}", "nested escaped error");
    fs::remove_all(directory);
    std::cout << checks << " protocol checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    fs::remove_all(directory);
    return 1;
  }
}

