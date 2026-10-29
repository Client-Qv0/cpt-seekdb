/*
 * Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#define USING_LOG_PREFIX SQL_ENG
#include "sql/engine/basic/file/file_json_reader.h"
#include "common/json_type/ob_json_base.h"
#include "common/json_type/ob_json_common.h"
#include <cmath>

namespace oceanbase {
namespace sql {
using namespace common;

int FileJsonReader::open(const ObString &path)
{
  close();
  ObCsvOptions options;
  options.header_ = false;
  options.delimiter_ = '\0';
  options.quote_ = '\0';
  options.escape_ = '\0';
  return lines_.open(path, options);
}

void FileJsonReader::close()
{
  lines_.close();
  columns_.reset();
  schema_allocator_.reset();
  row_allocator_.reset();
  batch_allocator_.reset();
  inferred_rows_ = 0;
  inferred_ = false;
}

int64_t FileJsonReader::find_column(const ObString &name) const
{
  int64_t index = -1;
  for (int64_t i = 0; index < 0 && i < columns_.count(); ++i) {
    if (name == columns_.at(i).name_) {
      index = i;
    }
  }
  return index;
}

int FileJsonReader::read_object(ObJsonObject *&object, bool &eof)
{
  int ret = OB_SUCCESS;
  object = nullptr;
  eof = false;
  row_allocator_.reuse();
  while (OB_SUCC(ret) && !eof && object == nullptr) {
    ObArray<ObString> cells;
    ObArray<uint8_t> nulls;
    int64_t rows = 0;
    if (OB_FAIL(lines_.next_batch(1, cells, nulls, rows))) {
    } else if (rows == 0) {
      eof = true;
    } else if (cells.count() != 1) {
      ret = OB_INVALID_DATA;
    } else {
      ObString line = cells.at(0);
      bool blank = true;
      for (int64_t i = 0; blank && i < line.length(); ++i) {
        const char c = line.ptr()[i];
        blank = c == ' ' || c == '\t' || c == '\r' || c == '\n';
      }
      if (!blank) {
        ObIJsonBase *node = nullptr;
        if (OB_FAIL(ObJsonBaseFactory::get_json_base(&row_allocator_, line,
                    ObJsonInType::JSON_TREE, ObJsonInType::JSON_TREE, node))) {
        } else if (OB_ISNULL(node) || node->json_type() != ObJsonNodeType::J_OBJECT) {
          ret = OB_INVALID_DATA;
        } else {
          object = static_cast<ObJsonObject *>(node);
        }
      }
    }
  }
  return ret;
}

int FileJsonReader::field_value(ObJsonNode *value, ObString &text, ObFileColumnType &type)
{
  int ret = OB_SUCCESS;
  type = OB_FILE_COL_NULL;
  text.reset();
  if (value == nullptr || value->json_type() == ObJsonNodeType::J_NULL) {
  } else if (value->json_type() == ObJsonNodeType::J_OBJECT
             || value->json_type() == ObJsonNodeType::J_ARRAY) {
    ret = OB_NOT_SUPPORTED;
  } else if (value->json_type() == ObJsonNodeType::J_STRING) {
    text = static_cast<ObJsonString *>(value)->get_str();
    const ObFileColumnType candidate = ObFileTypeInfer::detect(text.ptr(), text.length());
    type = candidate == OB_FILE_COL_DATE || candidate == OB_FILE_COL_DATETIME
           ? candidate : OB_FILE_COL_VARCHAR;
  } else {
    if (value->json_type() == ObJsonNodeType::J_BOOLEAN) {
      type = OB_FILE_COL_BOOLEAN;
    } else if (value->is_number()) {
      double number = 0;
      if (OB_FAIL(value->to_double(number))) {
      } else if (!std::isfinite(number)) {
        ret = OB_INVALID_DATA;
      } else {
        type = value->json_type() == ObJsonNodeType::J_INT
               || (value->json_type() == ObJsonNodeType::J_UINT && value->get_uint() <= INT64_MAX)
               ? OB_FILE_COL_BIGINT : OB_FILE_COL_DOUBLE;
      }
    } else {
      ret = OB_INVALID_DATA;
    }
    if (OB_SUCC(ret)) {
      ObJsonBuffer buffer(&row_allocator_);
      if (OB_FAIL(value->print(buffer, 0))) {
      } else {
        text = buffer.string();
      }
    }
  }
  return ret;
}

int FileJsonReader::infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns)
{
  int ret = OB_SUCCESS;
  columns.reuse();
  columns_.reuse();
  schema_allocator_.reuse();
  inferred_rows_ = 0;
  inferred_ = false;
  bool eof = false;
  if (OB_FAIL(lines_.begin_scan())) {
  }
  while (OB_SUCC(ret) && !eof) {
    ObJsonObject *object = nullptr;
    if (OB_FAIL(read_object(object, eof))) {
    } else if (!eof) {
      for (int64_t i = 0; i < columns_.count(); ++i) {
        ++columns_.at(i).null_count_;
      }
      for (int64_t i = 0; OB_SUCC(ret) && i < object->element_count(); ++i) {
        ObString key;
        ObString text;
        ObFileColumnType type;
        if (OB_FAIL(object->get_key(i, key))) {
        } else if (OB_FAIL(field_value(object->get_value(i), text, type))) {
        } else {
          int64_t index = find_column(key);
          if (index < 0) {
            ObFileColumnSchema column;
            column.null_count_ = inferred_rows_ + 1;
            for (int64_t j = 0; OB_SUCC(ret) && j < columns_.count(); ++j) {
              if (key.case_compare(columns_.at(j).name_) == 0) { ret = OB_INVALID_DATA; }
            }
            if (OB_FAIL(ret)) {
            } else if (columns_.count() >= 4096 || key.empty()) {
              ret = OB_INVALID_DATA;
            } else if (OB_FAIL(ob_write_string(schema_allocator_, key, column.name_))) {
            } else if (OB_FAIL(columns_.push_back(column))) {
            } else {
              index = columns_.count() - 1;
            }
          }
          if (OB_SUCC(ret)) {
            auto &column = columns_.at(index);
            column.type_ = ObFileTypeInfer::merge(column.type_, type);
            column.max_length_ = MAX(column.max_length_, text.length());
            if (type != OB_FILE_COL_NULL) {
              --column.null_count_;
            }
          }
        }
      }
      ++inferred_rows_;
    }
  }
  if (OB_SUCC(ret) && columns_.empty()) {
    ret = OB_INVALID_DATA;
  }
  for (int64_t i = 0; OB_SUCC(ret) && i < columns_.count(); ++i) {
    auto &column = columns_.at(i);
    column.nullable_ = column.null_count_ > 0;
    ObFileColumnSchema copy = column;
    if (OB_FAIL(ob_write_string(allocator, column.name_, copy.name_))) {
    } else if (OB_FAIL(columns.push_back(copy))) {
    }
  }
  inferred_ = OB_SUCC(ret);
  return ret;
}

int FileJsonReader::begin_scan()
{
  return inferred_ ? lines_.begin_scan() : OB_NOT_INIT;
}

int FileJsonReader::next_batch(int64_t max_rows, ObArray<ObString> &cells,
                              ObArray<uint8_t> &nulls, int64_t &rows)
{
  int ret = OB_SUCCESS;
  rows = 0;
  cells.reuse();
  nulls.reuse();
  batch_allocator_.reuse();
  int64_t bytes = 0;
  bool eof = false;
  if (!inferred_ || max_rows <= 0) {
    ret = OB_INVALID_ARGUMENT;
  }
  while (OB_SUCC(ret) && !eof && rows < max_rows && bytes < 8 * 1024 * 1024) {
    ObJsonObject *object = nullptr;
    if (OB_FAIL(read_object(object, eof))) {
    } else if (!eof) {
      for (int64_t i = 0; OB_SUCC(ret) && i < columns_.count(); ++i) {
        ObString text;
        ObString copy;
        ObFileColumnType type;
        if (OB_FAIL(field_value(object->get_value(columns_.at(i).name_), text, type))) {
        } else if (OB_FAIL(ob_write_string(batch_allocator_, text, copy))) {
        } else if (OB_FAIL(cells.push_back(copy))) {
        } else if (OB_FAIL(nulls.push_back(type == OB_FILE_COL_NULL ? 1 : 0))) {
        } else {
          bytes += text.length();
        }
      }
      ++rows;
    }
  }
  if (OB_FAIL(ret)) {
    rows = 0;
    cells.reuse();
    nulls.reuse();
  }
  return ret;
}

} // namespace sql
} // namespace oceanbase
