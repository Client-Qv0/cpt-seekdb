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

#include <stdio.h>

#include "lib/ob_define.h"
#include "lib/string/ob_string.h"
#include "lib/string/ob_string_buffer.h"
#include "lib/allocator/ob_allocator.h"
#include "lib/allocator/page_arena.h"
#include "lib/container/ob_array.h"
#include "sql/engine/basic/file/ob_file_type_infer.h"

namespace oceanbase
{
namespace sql
{

struct ObCsvOptions
{
  char delimiter_ = ',';
  bool header_ = true;
  char quote_ = '"';
  char escape_ = '"';               // "" is used to escape a quote inside a quoted field
  ObString null_str_;               // empty means: only an empty field is NULL
  int64_t max_field_len_ = 16 * 1024 * 1024;
};

// Streaming CSV reader: a 64KB sliding buffer is used, the whole file is never
// loaded into memory.  Both schema inference and batch scanning are streaming,
// one record at a time.
//
// Lifetime of the returned ObString cells is until the next call of
// next_batch()/close(), they point into the per-batch arena of the reader.
class ObFileCsvReader : public IFileRowReader
{
public:
  ObFileCsvReader();
  ~ObFileCsvReader();

  // open the file and remember its size / mtime for change detection.
  int open(const ObString &path, const ObCsvOptions &options, bool metadata_only = false);
  int check_unchanged() const;
  static int check_secure_path(const ObString &path, const ObString &root);
  // full streaming scan: read the header (c1..cN when header_ is false), then
  // infer the type of every column from all the data rows.
  int infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns);
  // rewind to the first data row (the header row is skipped).
  int begin_scan();
  // fetch up to max_rows rows, cells are flattened by row
  // (row_count * column_count) and nulls hold 1 for a NULL cell.
  int next_batch(const int64_t max_rows, ObArray<ObString> &cells,
                 ObArray<uint8_t> &nulls, int64_t &row_count);
  // rewind to the first data row, same as begin_scan().
  int rescan();
  void close();

  int64_t column_count() const { return column_count_; }
  int64_t inferred_rows() const { return inferred_rows_; }
  ObString column_name(int64_t index) const override { return get_column_name(index); }
  int signature(ObIAllocator &allocator, ObString &value) const override;
  int column_index(const ObString &name, int64_t &index) const;

private:
  struct FileMeta
  {
    int64_t size_;
    int64_t mtime_;
    int64_t mtime_ns_ = 0;
    uint64_t inode_ = 0;
    uint64_t device_ = 0;
    bool valid_;
    FileMeta() : size_(0), mtime_(0), valid_(false) {}
    bool operator==(const FileMeta &other) const
    {
      return valid_ && other.valid_ && size_ == other.size_ && mtime_ == other.mtime_
             && mtime_ns_ == other.mtime_ns_ && inode_ == other.inode_ && device_ == other.device_;
    }
  };

private:
  int stat_file(FileMeta &meta) const;
  // read the header row (or the first row when header_ is false) and build the
  // column names, also computes data_start_offset_ / data_offset_.
  int load_header();
  int seek_to(const int64_t offset);
  // refill the sliding buffer, unconsumed bytes are kept at the front.
  int fill_more();
  int peek(const int64_t ahead, bool &has_char, char &c);
  // parse exactly one record starting at the current position.
  // eof is true when there is no more record, blank is true for an empty line.
  int read_record(bool &eof, bool &blank);
  // parse exactly one field, appending its (unescaped) content to rec_buf_.
  int parse_field(const int64_t field_start, bool &quoted, bool &record_end);
  int append_field_char(const char c);
  int append_column_name(const int64_t field_off, const int64_t field_len, const int64_t index);
  bool is_null_field(const int64_t field_off, const int64_t field_len, const bool quoted) const;
  ObString get_column_name(const int64_t index) const;
  // copy the current record into the batch arena and append its cells.
  int emit_row(ObArray<ObString> &cells, ObArray<uint8_t> &nulls);

private:
  static constexpr int64_t READ_BUFFER_SIZE = 64 * 1024;
  static constexpr int64_t MAX_PATH_LENGTH = 1024;

  FILE *fp_;
  ObCsvOptions options_;
  char path_buf_[MAX_PATH_LENGTH];
  ObString path_;              // points into path_buf_
  bool opened_;
  bool scanning_;
  bool header_loaded_;
  int64_t column_count_;
  int64_t inferred_rows_;
  int64_t data_start_offset_;  // start of the first record (BOM already skipped)
  int64_t data_offset_;        // start of the first data row
  FileMeta meta_;

  // sliding read buffer, bytes [buf_start_offset_, buf_start_offset_ + buf_len_)
  char buf_[READ_BUFFER_SIZE];
  int64_t buf_len_;
  int64_t buf_start_offset_;
  int64_t pos_;
  bool eof_;
  int64_t record_no_;

  // one record: concatenated field content + per field offset / length / quoted
  ObArenaAllocator buf_arena_;
  ObStringBuffer rec_buf_;
  ObArray<int64_t> rec_off_;
  ObArray<int64_t> rec_len_;
  ObArray<uint8_t> rec_quoted_;
  // column names: concatenated bytes + per column offset / length
  ObStringBuffer name_buf_;
  ObArray<int64_t> name_off_;
  ObArray<int64_t> name_len_;
  // storage of the cells of the batch being returned
  ObArenaAllocator batch_arena_;
};

} // end namespace sql
} // end namespace oceanbase
