/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#pragma once

#include <string.h>
#include "lib/ob_define.h"
#include "common/sql_mode/ob_sql_mode.h"
#include "lib/ob_errno.h"
#include "lib/string/ob_string.h"
#include "lib/string/ob_sql_string.h"
#include "lib/allocator/ob_allocator.h"
#include "lib/utility/ob_print_utils.h"

namespace oceanbase
{
namespace share
{

////////////////////////////////////////////////////////////////////////////////
// AI COLUMN (asynchronous AI column)
//
// An AI column is a regular user visible result column that also owns three
// hidden companion columns, all named after the *result column name* so that a
// table schema is self describing (no O(1) lookup table is needed and the
// mapping survives a restart):
//
//   __ai_state_<col>   : int      AI column state of this row
//                                 1 = PENDING, 2 = READY, 3 = FAILED
//   __ai_request_<col> : varchar  in-flight request identity of this row
//   __ai_spec_<col>    : varchar  the persisted computation spec of this column
//
// The spec text is stored in the *column comment* of `__ai_spec_<col>`: the
// comment is persisted in `__all_column` for free, which lets the DDL layer
// publish `__all_ai_column` rows after the table schema is committed without
// any extra in-memory channel. `__all_ai_column` remains the authoritative,
// queryable metadata (see chapter 2.1 of the AI COLUMN spec).
////////////////////////////////////////////////////////////////////////////////

const char *const AI_COLUMN_STATE_PREFIX = "__ai_state_";
const char *const AI_COLUMN_REQUEST_PREFIX = "__ai_request_";
const char *const AI_COLUMN_SPEC_PREFIX = "__ai_spec_";
const char *const AI_COLUMN_INSTRUCTION_KEY = "__ai_column_instruction";

// state encoding of `__ai_state_<col>`
const int64_t AI_COLUMN_STATE_PENDING = 1;
const int64_t AI_COLUMN_STATE_READY = 2;
const int64_t AI_COLUMN_STATE_FAILED = 3;

// `__all_ai_column.result_type`: how the model answer is converted and stored
enum ObAiColumnResultType
{
  AI_COLUMN_RESULT_INVALID = 0,
  AI_COLUMN_RESULT_JSON = 1,
  AI_COLUMN_RESULT_INTEGER = 2,
  AI_COLUMN_RESULT_STRING = 3,
  AI_COLUMN_RESULT_VECTOR = 4,
};

// The type instruction is persisted together with the AI expression and is sent
// to the model as the `system` message when the column is computed, therefore
// the wording of the json/integer variants is part of the observable contract:
//   - json result column    -> must contain "Return exactly one valid JSON value"
//   - integer result column -> must contain "base-10 integer"
inline const char *ai_column_result_type_instruction(const int64_t result_type)
{
  const char *instruction = NULL;
  switch (result_type) {
    case AI_COLUMN_RESULT_JSON:
      instruction = "Return exactly one valid JSON value only.";
      break;
    case AI_COLUMN_RESULT_INTEGER:
      instruction = "Return exactly one base-10 integer value only.";
      break;
    case AI_COLUMN_RESULT_VECTOR:
      instruction = "Return the embedding as a JSON array of numbers only.";
      break;
    case AI_COLUMN_RESULT_STRING:
    default:
      instruction = "Return the answer as plain text only.";
      break;
  }
  return instruction;
}

// The persisted, normalized form of an AI column definition:
// "<ai function call as written by the user> => <result type instruction>".
// It is what `__all_ai_column.normalized_expr` exposes and what the request
// builder sends to the model.
inline int build_ai_column_normalized_expr(common::ObIAllocator &alloc,
                                           const common::ObString &expr_text,
                                           const int64_t result_type,
                                           common::ObString &normalized_expr)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  const char *instruction = ai_column_result_type_instruction(result_type);
  const char *fallback = "<ai column expression>";
  const char *expr_ptr = expr_text.empty() ? fallback : expr_text.ptr();
  const int64_t expr_len = expr_text.empty() ? static_cast<int64_t>(strlen(fallback))
                                             : static_cast<int64_t>(expr_text.length());
  if (OB_ISNULL(expr_ptr) || OB_ISNULL(instruction)) {
    ret = OB_INVALID_ARGUMENT;
    SHARE_LOG(WARN, "invalid argument to build ai column normalized expr", K(ret));
  } else if (OB_FAIL(buf.append(expr_ptr, expr_len))) {
    SHARE_LOG(WARN, "failed to append ai column expression text", K(ret));
  } else if (OB_FAIL(buf.append(" => "))) {
    SHARE_LOG(WARN, "failed to append ai column type separator", K(ret));
  } else if (OB_FAIL(buf.append(instruction))) {
    SHARE_LOG(WARN, "failed to append ai column type instruction", K(ret));
  } else if (OB_FAIL(ob_write_string(alloc,
                                     common::ObString(buf.length(), buf.ptr()),
                                     normalized_expr))) {
    SHARE_LOG(WARN, "failed to write ai column normalized expr", K(ret));
  }
  return ret;
}

// "__ai_state_" + result column name
inline int build_ai_hidden_column_name(common::ObIAllocator &alloc,
                                       const char *prefix,
                                       const common::ObString &result_column_name,
                                       common::ObString &hidden_column_name)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  if (OB_ISNULL(prefix) || result_column_name.empty()) {
    ret = OB_INVALID_ARGUMENT;
    SHARE_LOG(WARN, "invalid argument to build ai hidden column name", K(ret));
  } else if (OB_FAIL(buf.append(prefix))) {
    SHARE_LOG(WARN, "failed to append ai hidden column prefix", K(ret));
  } else if (OB_FAIL(buf.append(result_column_name.ptr(), result_column_name.length()))) {
    SHARE_LOG(WARN, "failed to append ai hidden column suffix", K(ret));
  } else if (buf.length() > OB_MAX_COLUMN_NAME_LENGTH) {
    ret = OB_WRONG_COLUMN_NAME;
    SHARE_LOG(WARN, "ai hidden column name is too long", K(ret), K(buf.length()));
  } else if (OB_FAIL(ob_write_string(alloc,
                                     common::ObString(buf.length(), buf.ptr()),
                                     hidden_column_name))) {
    SHARE_LOG(WARN, "failed to write ai hidden column name", K(ret));
  }
  return ret;
}

// Return true and the "<result column name>" part if `column_name` carries the
// given AI hidden column prefix.
inline bool get_ai_hidden_column_suffix(const common::ObString &column_name,
                                        const char *prefix,
                                        common::ObString &result_column_name)
{
  bool bret = false;
  result_column_name.reset();
  if (NULL != prefix && !column_name.empty()) {
    const int64_t prefix_len = static_cast<int64_t>(strlen(prefix));
    if (column_name.length() > prefix_len && 0 == MEMCMP(column_name.ptr(), prefix, prefix_len)) {
      result_column_name.assign_ptr(column_name.ptr() + prefix_len,
                                    static_cast<int32_t>(column_name.length() - prefix_len));
      bret = true;
    }
  }
  return bret;
}

////////////////////////////////////////////////////////////////////////////////
// ObAiColumnSpec: everything the server needs to know about one AI column.
// Carried from the resolver to the DDL layer through the `__ai_spec_<col>`
// column comment, and published to `__all_ai_column`.
////////////////////////////////////////////////////////////////////////////////
class ObAiColumnSpec
{
public:
  ObAiColumnSpec() { reset(); }
  ~ObAiColumnSpec() { reset(); }
  void reset()
  {
    result_column_name_.reset();
    model_name_.reset();
    ai_func_name_.reset();
    normalized_expr_.reset();
    dependencies_.reset();
    sync_mode_.reset();
    result_column_id_ = OB_INVALID_ID;
    state_column_id_ = OB_INVALID_ID;
    request_column_id_ = OB_INVALID_ID;
    result_spec_column_id_ = OB_INVALID_ID;
    max_retries_ = 0;
    result_type_ = AI_COLUMN_RESULT_INVALID;
    sql_mode_ = DEFAULT_MYSQL_MODE;
  }
  bool is_valid() const { return !result_column_name_.empty() && !ai_func_name_.empty(); }
  int assign(const ObAiColumnSpec &other)
  {
    int ret = OB_SUCCESS;
    result_column_name_ = other.result_column_name_;
    model_name_ = other.model_name_;
    ai_func_name_ = other.ai_func_name_;
    normalized_expr_ = other.normalized_expr_;
    dependencies_ = other.dependencies_;
    sync_mode_ = other.sync_mode_;
    result_column_id_ = other.result_column_id_;
    state_column_id_ = other.state_column_id_;
    request_column_id_ = other.request_column_id_;
    result_spec_column_id_ = other.result_spec_column_id_;
    max_retries_ = other.max_retries_;
    result_type_ = other.result_type_;
    sql_mode_ = other.sql_mode_;
    return ret;
  }
  TO_STRING_KV(K_(result_column_name), K_(model_name), K_(ai_func_name),
               K_(normalized_expr), K_(sync_mode), K_(result_column_id),
               K_(state_column_id), K_(request_column_id),
               K_(result_spec_column_id), K_(max_retries), K_(result_type));

public:
  common::ObString result_column_name_;
  common::ObString model_name_;
  common::ObString ai_func_name_;
  common::ObString normalized_expr_;
  // Length-prefixed column names: "<byte length>:<name>...". Names may
  // contain separators, quotes or newlines without becoming ambiguous.
  common::ObString dependencies_;
  common::ObString sync_mode_;
  uint64_t result_column_id_;
  uint64_t state_column_id_;
  uint64_t request_column_id_;
  uint64_t result_spec_column_id_;
  int64_t max_retries_;
  int64_t result_type_;
  uint64_t sql_mode_;
};

////////////////////////////////////////////////////////////////////////////////
// The spec is persisted as a flat "key=value" list, one pair per line, with
// '\\' and '\n' escaped inside values. It is written into the comment of the
// `__ai_spec_<col>` hidden column, i.e. it is only read back by the server.
////////////////////////////////////////////////////////////////////////////////
inline int escape_ai_spec_value(common::ObSqlString &buf, const common::ObString &value)
{
  int ret = OB_SUCCESS;
  for (int64_t i = 0; OB_SUCC(ret) && i < value.length(); ++i) {
    const char c = value.ptr()[i];
    if ('\\' == c) {
      ret = buf.append("\\\\", 2);
    } else if ('\n' == c) {
      ret = buf.append("\\n", 2);
    } else {
      ret = buf.append(&c, 1);
    }
  }
  return ret;
}

inline int append_ai_spec_string(common::ObSqlString &buf, const char *key,
                                 const common::ObString &value)
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(buf.append(key)) || OB_FAIL(buf.append("=")) ||
      OB_FAIL(escape_ai_spec_value(buf, value)) || OB_FAIL(buf.append("\n"))) {
    SHARE_LOG(WARN, "failed to append ai column spec field", K(ret), KCSTRING(key));
  }
  return ret;
}

inline int serialize_ai_column_spec(common::ObIAllocator &alloc,
                                    const ObAiColumnSpec &spec,
                                    common::ObString &serialized)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  common::ObSqlString num;
  if (!spec.is_valid()) {
    ret = OB_INVALID_ARGUMENT;
    SHARE_LOG(WARN, "ai column spec is not valid", K(ret), K(spec));
  } else if (OB_FAIL(append_ai_spec_string(buf, "result_column", spec.result_column_name_))) {
  } else if (OB_FAIL(append_ai_spec_string(buf, "model", spec.model_name_))) {
  } else if (OB_FAIL(append_ai_spec_string(buf, "func", spec.ai_func_name_))) {
  } else if (OB_FAIL(append_ai_spec_string(buf, "expr", spec.normalized_expr_))) {
  } else if (OB_FAIL(append_ai_spec_string(buf, "dependencies", spec.dependencies_))) {
  } else if (OB_FAIL(append_ai_spec_string(buf, "sync_mode", spec.sync_mode_))) {
  } else if (OB_FAIL(num.append_fmt("max_retries=%ld\nresult_type=%ld\nsql_mode=%lu\n",
                                    spec.max_retries_, spec.result_type_, spec.sql_mode_))) {
    SHARE_LOG(WARN, "failed to append ai column spec numbers", K(ret));
  } else if (OB_FAIL(buf.append(num.ptr(), num.length()))) {
    SHARE_LOG(WARN, "failed to append ai column spec numbers", K(ret));
  } else if (OB_FAIL(ob_write_string(alloc,
                                     common::ObString(buf.length(), buf.ptr()),
                                     serialized))) {
    SHARE_LOG(WARN, "failed to write serialized ai column spec", K(ret));
  }
  return ret;
}

// Copy an escaped value into `out` (allocator owned).
inline int unescape_ai_spec_value(common::ObIAllocator &alloc,
                                  const char *ptr, const int64_t len,
                                  common::ObString &out)
{
  int ret = OB_SUCCESS;
  common::ObSqlString buf;
  for (int64_t i = 0; OB_SUCC(ret) && i < len; ++i) {
    const char c = ptr[i];
    if ('\\' == c && i + 1 < len) {
      const char next = ptr[++i];
      ret = buf.append('n' == next ? "\n" : &next, 1);
    } else {
      ret = buf.append(&c, 1);
    }
  }
  if (OB_SUCC(ret) && OB_FAIL(ob_write_string(alloc,
                                              common::ObString(buf.length(), buf.ptr()),
                                              out))) {
    SHARE_LOG(WARN, "failed to write unescaped ai spec value", K(ret));
  }
  return ret;
}

inline int parse_ai_spec_integer(const common::ObString &value, int64_t &number)
{
  int ret = OB_SUCCESS;
  number = 0;
  if (value.empty()) {
    ret = OB_INVALID_ARGUMENT;
  }
  for (int64_t i = 0; OB_SUCC(ret) && i < value.length(); ++i) {
    const char c = value.ptr()[i];
    if (c < '0' || c > '9' || number > (INT64_MAX - (c - '0')) / 10) {
      ret = OB_INVALID_ARGUMENT;
    } else {
      number = number * 10 + c - '0';
    }
  }
  return ret;
}

// The type instruction is a fixed suffix, not part of the executable SQL.
// Match from the end so a user string containing " => " remains intact.
inline common::ObString ai_column_expression(const ObAiColumnSpec &spec)
{
  const char *instruction = ai_column_result_type_instruction(spec.result_type_);
  const int64_t suffix_len = strlen(instruction) + 4;
  const common::ObString &text = spec.normalized_expr_;
  common::ObString expression = text;
  if (text.length() > suffix_len
      && 0 == MEMCMP(text.ptr() + text.length() - suffix_len, " => ", 4)
      && 0 == MEMCMP(text.ptr() + text.length() - suffix_len + 4,
                    instruction, suffix_len - 4)) {
    expression.assign_ptr(text.ptr(), text.length() - suffix_len);
  }
  return expression;
}

inline int deserialize_ai_column_spec(const common::ObString &serialized,
                                      common::ObIAllocator &alloc,
                                      ObAiColumnSpec &spec)
{
  int ret = OB_SUCCESS;
  spec.reset();
  if (serialized.empty()) {
    ret = OB_INVALID_ARGUMENT;
    SHARE_LOG(WARN, "empty ai column spec text", K(ret));
  }
  int64_t pos = 0;
  while (OB_SUCC(ret) && pos < serialized.length()) {
    int64_t line_end = pos;
    while (line_end < serialized.length() && '\n' != serialized.ptr()[line_end]) {
      ++line_end;
    }
    const char *line = serialized.ptr() + pos;
    const int64_t line_len = line_end - pos;
    int64_t eq = 0;
    while (eq < line_len && '=' != line[eq]) {
      ++eq;
    }
    if (eq >= line_len) {
      // ignore a malformed line
    } else {
      const char *key = line;
      const int64_t key_len = eq;
      const char *val = line + eq + 1;
      const int64_t val_len = line_len - eq - 1;
      common::ObString value;
      if (OB_FAIL(unescape_ai_spec_value(alloc, val, val_len, value))) {
      } else if (4 == key_len && 0 == MEMCMP(key, "expr", 4)) {
        spec.normalized_expr_ = value;
      } else if (4 == key_len && 0 == MEMCMP(key, "func", 4)) {
        spec.ai_func_name_ = value;
      } else if (12 == key_len && 0 == MEMCMP(key, "dependencies", 12)) {
        spec.dependencies_ = value;
      } else if (5 == key_len && 0 == MEMCMP(key, "model", 5)) {
        spec.model_name_ = value;
      } else if (9 == key_len && 0 == MEMCMP(key, "sync_mode", 9)) {
        spec.sync_mode_ = value;
      } else if (11 == key_len && 0 == MEMCMP(key, "max_retries", 11)) {
        ret = parse_ai_spec_integer(value, spec.max_retries_);
      } else if (11 == key_len && 0 == MEMCMP(key, "result_type", 11)) {
        ret = parse_ai_spec_integer(value, spec.result_type_);
      } else if (8 == key_len && 0 == MEMCMP(key, "sql_mode", 8)) {
        int64_t mode = 0;
        if (OB_FAIL(parse_ai_spec_integer(value, mode))) {
        } else { spec.sql_mode_ = static_cast<uint64_t>(mode); }
      } else if (13 == key_len && 0 == MEMCMP(key, "result_column", 13)) {
        spec.result_column_name_ = value;
      } else {
        // unknown field, ignore
      }
    }
    pos = line_end + 1;
  }
  if (OB_SUCC(ret) && !spec.is_valid()) {
    ret = OB_INVALID_ARGUMENT;
    SHARE_LOG(WARN, "deserialized ai column spec is not valid", K(ret), K(serialized));
  }
  return ret;
}

} // namespace share
} // namespace oceanbase
