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

#include "lib/ob_define.h"
#include "lib/string/ob_string.h"

namespace oceanbase
{
namespace sql
{

// Physical (candidate) type of one file column.  The order inside the
// numeric / temporal groups is used by ObFileTypeInfer::merge() as a
// widening ladder, do not reorder without updating merge().
enum ObFileColumnType : uint8_t
{
  OB_FILE_COL_NULL = 0,
  OB_FILE_COL_BOOLEAN = 1,
  OB_FILE_COL_BIGINT = 2,
  OB_FILE_COL_DOUBLE = 3,
  OB_FILE_COL_DATE = 4,
  OB_FILE_COL_DATETIME = 5,
  OB_FILE_COL_VARCHAR = 6,
};

struct ObFileColumnSchema
{
  ObString name_;
  ObFileColumnType type_;
  bool nullable_;
  ObFileColumnSchema()
    : name_(),
      type_(OB_FILE_COL_NULL),
      nullable_(false)
  {}
};

// Deterministic, single pass type inference on raw CSV fields.
class ObFileTypeInfer
{
public:
  // One raw field (already unescaped, may be nullptr when len <= 0).
  // An empty field (or a field made of blanks only) is OB_FILE_COL_NULL.
  static ObFileColumnType detect(const char *ptr, const int64_t len);
  // widen two column types into the type that can hold both.
  static ObFileColumnType merge(ObFileColumnType a, ObFileColumnType b);
  // name used by DESCRIBE
  static const char *type_name(ObFileColumnType type);

private:
  static bool is_blank(const char *ptr, const int64_t len);
  static bool is_digit(const char c);
  static bool is_boolean(const char *ptr, const int64_t len);
  // BIGINT / DOUBLE / VARCHAR (also rejects nan, inf, hex and trailing junk)
  static ObFileColumnType detect_number(const char *ptr, const int64_t len);
  // true if the pure integer text fits into int64_t
  static bool is_int64_value(const char *ptr, const int64_t len);
  static bool is_date(const char *ptr, const int64_t len);
  static bool is_datetime(const char *ptr, const int64_t len);
  static bool is_leap_year(const int64_t year);
  static int64_t days_in_month(const int64_t year, const int64_t month);
  // parse exactly len digits, -1 if any char is not a decimal digit
  static int64_t read_digits(const char *ptr, const int64_t len);
  static bool is_numeric_type(const ObFileColumnType type);
  static bool is_temporal_type(const ObFileColumnType type);
  static int64_t numeric_rank(const ObFileColumnType type);
};

} // end namespace sql
} // end namespace oceanbase
