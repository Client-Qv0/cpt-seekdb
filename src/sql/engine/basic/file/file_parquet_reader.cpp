/* Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
#define USING_LOG_PREFIX SQL_ENG
#include "sql/engine/basic/file/file_parquet_reader.h"
#include "share/ob_errno.h"

namespace oceanbase { namespace sql {
using namespace common;
void FileParquetReader::close()
{
  seek_parquet_close(handle_); handle_ = nullptr;
  guard_.close(); columns_.reset();
  schema_allocator_.reset(); batch_allocator_.reset();
}

int FileParquetReader::open(const ObString &path)
{
  int ret = OB_SUCCESS;
  close();
  ObCsvOptions options;
  if (OB_FAIL(guard_.open(path, options, true))) {
  } else if (OB_ISNULL(handle_ = seek_parquet_open(
                   reinterpret_cast<const uint8_t *>(path.ptr()), path.length()))) {
    ret = OB_INVALID_DATA;
    LOG_USER_ERROR(OB_INVALID_DATA, "invalid, unsupported or oversized Parquet row group");
  } else {
    for (int64_t i = 0; OB_SUCC(ret) && i < seek_parquet_columns(handle_); ++i) {
      SeekParquetCell name;
      int32_t type = 0;
      uint8_t nullable = 0;
      ObFileColumnSchema column;
      if (seek_parquet_column(handle_, i, &name, &type, &nullable) != 0) {
        ret = OB_INVALID_DATA;
      } else if (OB_FAIL(ob_write_string(schema_allocator_,
              ObString(name.length, reinterpret_cast<const char *>(name.data)), column.name_))) {
      } else {
        column.type_ = static_cast<ObFileColumnType>(type);
        column.nullable_ = nullable != 0;
        column.null_count_ = nullable ? MAX(1, inferred_rows()) : 0;
        column.max_length_ = OB_MAX_VARCHAR_LENGTH;
        ret = columns_.push_back(column);
      }
    }
    if (OB_SUCC(ret)) { ret = guard_.check_unchanged(); }
  }
  if (OB_FAIL(ret)) { close(); }
  return ret;
}

int FileParquetReader::infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns)
{
  int ret = OB_SUCCESS;
  columns.reuse();
  for (int64_t i = 0; OB_SUCC(ret) && i < columns_.count(); ++i) {
    ObFileColumnSchema column = columns_.at(i);
    if (OB_FAIL(ob_write_string(allocator, column.name_, column.name_))) {
    } else { ret = columns.push_back(column); }
  }
  return ret;
}

int FileParquetReader::begin_scan()
{
  int ret = guard_.check_unchanged();
  if (OB_SUCC(ret) && seek_parquet_rewind(handle_) != 0) { ret = OB_INVALID_DATA; }
  return ret;
}

int FileParquetReader::project(const ObIArray<int64_t> &indices)
{
  ObArray<size_t> selected;
  int ret = OB_SUCCESS;
  for (int64_t i = 0; OB_SUCC(ret) && i < indices.count(); ++i) {
    ret = selected.push_back(static_cast<size_t>(indices.at(i)));
  }
  if (OB_SUCC(ret) && seek_parquet_project(handle_, selected.get_data(), selected.count()) != 0) {
    ret = OB_INVALID_ARGUMENT;
  }
  return ret;
}

int FileParquetReader::next_batch(int64_t max_rows, ObArray<ObString> &cells,
                                 ObArray<uint8_t> &nulls, int64_t &rows)
{
  int ret = max_rows > 0 ? guard_.check_unchanged() : OB_INVALID_ARGUMENT;
  cells.reuse(); nulls.reuse(); rows = 0; batch_allocator_.reuse();
  int64_t bytes = 0;
  bool eof = false;
  while (OB_SUCC(ret) && rows < max_rows && !eof && bytes < 8 * 1024 * 1024) {
    const SeekParquetCell *record = nullptr;
    const int status = seek_parquet_next(handle_, &record);
    if (status == 1) { eof = true; }
    else if (status != 0 || record == nullptr) { ret = OB_INVALID_DATA; }
    else {
      for (int64_t i = 0; OB_SUCC(ret) && i < column_count(); ++i) {
        ObString cell;
        const auto &value = record[i];
        if (!value.is_null) {
          ret = ob_write_string(batch_allocator_, ObString(value.length,
                      reinterpret_cast<const char *>(value.data)), cell);
          bytes += value.length;
        }
        if (OB_FAIL(ret)) {
        } else if (OB_FAIL(cells.push_back(cell))) {
        } else { ret = nulls.push_back(value.is_null); }
      }
      if (OB_SUCC(ret)) { ++rows; }
    }
  }
  if (OB_SUCC(ret)) { ret = guard_.check_unchanged(); }
  if (OB_FAIL(ret)) { cells.reuse(); nulls.reuse(); rows = 0; }
  return ret;
}
} }
