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
#include "share/ai_column/ob_ai_column_util.h"
#include "share/schema/ob_table_schema.h"

namespace oceanbase { namespace share {
inline const schema::ObColumnSchemaV2 *ai_column_spec_column(
    const schema::ObTableSchema &table, const common::ObString &name)
{
  for (auto it = table.column_begin(); it != table.column_end(); ++it) {
    common::ObString suffix;
    if ((*it)->is_hidden() && get_ai_hidden_column_suffix(
        (*it)->get_column_name_str(), AI_COLUMN_SPEC_PREFIX, suffix)
        && 0 == suffix.case_compare(name)) {
      return *it;
    }
  }
  return NULL;
}
inline bool ai_column_depends_on(const ObAiColumnSpec &spec, const common::ObString &name)
{
  int64_t pos = 0;
  const common::ObString &deps = spec.dependencies_;
  while (pos < deps.length()) {
    const int64_t start = pos;
    while (pos < deps.length() && deps.ptr()[pos] != ':') { ++pos; }
    int64_t len = 0;
    if (pos == deps.length() || OB_SUCCESS != parse_ai_spec_integer(
        common::ObString(pos - start, deps.ptr() + start), len)
        || len > deps.length() - pos - 1) {
      return false;
    }
    ++pos;
    if (0 == common::ObString(len, deps.ptr() + pos).case_compare(name)) { return true; }
    pos += len;
  }
  return false;
}
inline int ai_column_quote_identifier(common::ObSqlString &sql, const common::ObString &name)
{
  int ret = sql.append("`");
  for (int64_t i = 0; OB_SUCC(ret) && i < name.length(); ++i) {
    if ('`' == name.ptr()[i]) { ret = sql.append("``"); }
    else { ret = sql.append(name.ptr() + i, 1); }
  }
  if (OB_SUCC(ret)) { ret = sql.append("`"); }
  return ret;
}
inline int ai_column_sql_literal(common::ObSqlString &sql, const common::ObString &value)
{
  int ret = sql.append("X'");
  const char digits[] = "0123456789abcdef";
  for (int64_t i = 0; OB_SUCC(ret) && i < value.length(); ++i) {
    const unsigned char c = value.ptr()[i];
    const char pair[] = {digits[c >> 4], digits[c & 15]};
    ret = sql.append(pair, 2);
  }
  if (OB_SUCC(ret)) { ret = sql.append("'"); }
  return ret;
}
} }
