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

#define USING_LOG_PREFIX SQL_ENG

#include "sql/engine/basic/file/ob_file_type_infer.h"

namespace oceanbase
{
namespace sql
{

bool ObFileTypeInfer::is_digit(const char c)
{
  return c >= '0' && c <= '9';
}

// empty string or blanks only, the caller has already made sure the field is
// not quoted (a quoted field is always a real string).
bool ObFileTypeInfer::is_blank(const char *ptr, const int64_t len)
{
  bool blank = true;
  if (OB_ISNULL(ptr) || len <= 0) {
  } else {
    for (int64_t i = 0; blank && i < len; ++i) {
      const char c = ptr[i];
      if (' ' != c && '\t' != c && '\r' != c && '\n' != c && '\v' != c && '\f' != c) {
        blank = false;
      }
    }
  }
  return blank;
}

bool ObFileTypeInfer::is_boolean(const char *ptr, const int64_t len)
{
  bool is_bool = false;
  if (OB_ISNULL(ptr)) {
  } else if (4 == len) {
    is_bool = ('t' == (ptr[0] | 0x20)) && ('r' == (ptr[1] | 0x20))
              && ('u' == (ptr[2] | 0x20)) && ('e' == (ptr[3] | 0x20));
  } else if (5 == len) {
    is_bool = ('f' == (ptr[0] | 0x20)) && ('a' == (ptr[1] | 0x20))
              && ('l' == (ptr[2] | 0x20)) && ('s' == (ptr[3] | 0x20))
              && ('e' == (ptr[4] | 0x20));
  }
  return is_bool;
}

int64_t ObFileTypeInfer::read_digits(const char *ptr, const int64_t len)
{
  int64_t value = 0;
  bool valid = (NULL != ptr) && (len > 0);
  for (int64_t i = 0; valid && i < len; ++i) {
    if (!is_digit(ptr[i])) {
      valid = false;
    } else {
      value = value * 10 + (ptr[i] - '0');
    }
  }
  return valid ? value : -1;
}

bool ObFileTypeInfer::is_leap_year(const int64_t year)
{
  return (0 == year % 4 && 0 != year % 100) || 0 == year % 400;
}

int64_t ObFileTypeInfer::days_in_month(const int64_t year, const int64_t month)
{
  int64_t days = 0;
  if (month < 1 || month > 12) {
    days = 0;
  } else if (2 == month) {
    days = is_leap_year(year) ? 29 : 28;
  } else if (4 == month || 6 == month || 9 == month || 11 == month) {
    days = 30;
  } else {
    days = 31;
  }
  return days;
}

// YYYY-MM-DD, month in [1, 12] and day valid for that month / leap year.
bool ObFileTypeInfer::is_date(const char *ptr, const int64_t len)
{
  bool valid = false;
  if (OB_ISNULL(ptr) || 10 != len) {
  } else if ('-' != ptr[4] || '-' != ptr[7]) {
  } else {
    const int64_t year = read_digits(ptr, 4);
    const int64_t month = read_digits(ptr + 5, 2);
    const int64_t day = read_digits(ptr + 8, 2);
    if (year < 0 || month < 1 || month > 12 || day < 1) {
    } else if (day <= days_in_month(year, month)) {
      valid = true;
    }
  }
  return valid;
}

// YYYY-MM-DD HH:MM:SS, 'T' is accepted as the separator as well, an optional
// fraction of 1..9 digits is accepted and ignored.
bool ObFileTypeInfer::is_datetime(const char *ptr, const int64_t len)
{
  bool valid = false;
  if (OB_ISNULL(ptr) || len < 19) {
  } else if (' ' != ptr[10] && 'T' != ptr[10] && 't' != ptr[10]) {
  } else if (!is_date(ptr, 10)) {
  } else if (':' != ptr[13] || ':' != ptr[16]) {
  } else {
    const int64_t hour = read_digits(ptr + 11, 2);
    const int64_t minute = read_digits(ptr + 14, 2);
    const int64_t second = read_digits(ptr + 17, 2);
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) {
    } else if (19 == len) {
      valid = true;
    } else if ('.' != ptr[19]) {
    } else {
      const int64_t frac_len = len - 20;
      if (frac_len >= 1 && frac_len <= 9 && read_digits(ptr + 20, frac_len) >= 0) {
        valid = true;
      }
    }
  }
  return valid;
}

bool ObFileTypeInfer::is_int64_value(const char *ptr, const int64_t len)
{
  bool fits = true;
  int64_t i = 0;
  bool negative = false;
  if (OB_ISNULL(ptr) || len <= 0) {
    fits = false;
  } else {
    if ('+' == ptr[0] || '-' == ptr[0]) {
      negative = ('-' == ptr[0]);
      i = 1;
    }
    // 9223372036854775807 / -9223372036854775808
    const uint64_t limit = negative ? static_cast<uint64_t>(INT64_MAX) + 1UL
                                    : static_cast<uint64_t>(INT64_MAX);
    uint64_t value = 0;
    for (; fits && i < len; ++i) {
      if (!is_digit(ptr[i])) {
        fits = false;
      } else {
        const uint64_t digit = static_cast<uint64_t>(ptr[i] - '0');
        if (value > (limit - digit) / 10) {
          fits = false;
        } else {
          value = value * 10 + digit;
        }
      }
    }
  }
  return fits;
}

// [+-]?digits (BIGINT, or DOUBLE when it overflows int64)
// [+-]?digits[.digits][eE[+-]?digits] -> DOUBLE
// nan / inf / hex / anything with trailing chars -> VARCHAR
ObFileColumnType ObFileTypeInfer::detect_number(const char *ptr, const int64_t len)
{
  ObFileColumnType type = OB_FILE_COL_VARCHAR;
  bool valid = true;
  bool has_fraction = false;
  bool has_exponent = false;
  int64_t i = 0;
  if (OB_ISNULL(ptr) || len <= 0) {
    valid = false;
  } else {
    if ('+' == ptr[0] || '-' == ptr[0]) {
      i = 1;
    }
    const int64_t int_start = i;
    while (i < len && is_digit(ptr[i])) {
      ++i;
    }
    const int64_t int_len = i - int_start;
    const bool is_pure_int = (i == len);
    if (i < len && '.' == ptr[i]) {
      ++i;
      const int64_t frac_start = i;
      while (i < len && is_digit(ptr[i])) {
        ++i;
      }
      has_fraction = true;
      if (i == frac_start && 0 == int_len) {
        valid = false;  // a lone '.'
      }
    }
    if (valid && i < len && ('e' == ptr[i] || 'E' == ptr[i])) {
      ++i;
      if (i < len && ('+' == ptr[i] || '-' == ptr[i])) {
        ++i;
      }
      const int64_t exp_start = i;
      while (i < len && is_digit(ptr[i])) {
        ++i;
      }
      has_exponent = true;
      if (i == exp_start) {
        valid = false;  // '1e'
      }
    }
    if (!valid || i != len || (0 == int_len && !has_fraction)) {
      valid = false;
    } else if (is_pure_int && !has_exponent) {
      type = is_int64_value(ptr, len) ? OB_FILE_COL_BIGINT : OB_FILE_COL_DOUBLE;
    } else {
      type = OB_FILE_COL_DOUBLE;
    }
  }
  return valid ? type : OB_FILE_COL_VARCHAR;
}

ObFileColumnType ObFileTypeInfer::detect(const char *ptr, const int64_t len)
{
  ObFileColumnType type = OB_FILE_COL_VARCHAR;
  if (OB_ISNULL(ptr) || len <= 0) {
    type = OB_FILE_COL_NULL;
  } else if (is_blank(ptr, len)) {
    type = OB_FILE_COL_NULL;
  } else if (is_boolean(ptr, len)) {
    type = OB_FILE_COL_BOOLEAN;
  } else if (is_date(ptr, len)) {
    type = OB_FILE_COL_DATE;
  } else if (is_datetime(ptr, len)) {
    type = OB_FILE_COL_DATETIME;
  } else {
    type = detect_number(ptr, len);
  }
  return type;
}

bool ObFileTypeInfer::is_numeric_type(const ObFileColumnType type)
{
  return OB_FILE_COL_BOOLEAN == type
         || OB_FILE_COL_BIGINT == type
         || OB_FILE_COL_DOUBLE == type;
}

bool ObFileTypeInfer::is_temporal_type(const ObFileColumnType type)
{
  return OB_FILE_COL_DATE == type || OB_FILE_COL_DATETIME == type;
}

int64_t ObFileTypeInfer::numeric_rank(const ObFileColumnType type)
{
  int64_t rank = 0;
  if (OB_FILE_COL_BOOLEAN == type) {
    rank = 1;
  } else if (OB_FILE_COL_BIGINT == type) {
    rank = 2;
  } else if (OB_FILE_COL_DOUBLE == type) {
    rank = 3;
  }
  return rank;
}

ObFileColumnType ObFileTypeInfer::merge(ObFileColumnType a, ObFileColumnType b)
{
  ObFileColumnType type = OB_FILE_COL_VARCHAR;
  if (a == b) {
    type = a;
  } else if (OB_FILE_COL_NULL == a) {
    type = b;
  } else if (OB_FILE_COL_NULL == b) {
    type = a;
  } else if (OB_FILE_COL_VARCHAR == a || OB_FILE_COL_VARCHAR == b) {
    type = OB_FILE_COL_VARCHAR;
  } else if (is_numeric_type(a) && is_numeric_type(b)) {
    type = numeric_rank(a) >= numeric_rank(b) ? a : b;
  } else if (is_temporal_type(a) && is_temporal_type(b)) {
    type = OB_FILE_COL_DATETIME;  // DATE + DATETIME
  } else {
    // DATE + BIGINT, BOOLEAN + DATE, ...
    type = OB_FILE_COL_VARCHAR;
  }
  return type;
}

const char *ObFileTypeInfer::type_name(ObFileColumnType type)
{
  const char *name = "VARCHAR";
  switch (type) {
    case OB_FILE_COL_NULL:
      name = "NULL";
      break;
    case OB_FILE_COL_BOOLEAN:
      name = "BOOLEAN";
      break;
    case OB_FILE_COL_BIGINT:
      name = "BIGINT";
      break;
    case OB_FILE_COL_DOUBLE:
      name = "DOUBLE";
      break;
    case OB_FILE_COL_DATE:
      name = "DATE";
      break;
    case OB_FILE_COL_DATETIME:
      name = "DATETIME";
      break;
    case OB_FILE_COL_VARCHAR:
      name = "VARCHAR";
      break;
    default:
      name = "VARCHAR";
      break;
  }
  return name;
}

} // end namespace sql
} // end namespace oceanbase
