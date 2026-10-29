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

#pragma once

#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "common/json_type/ob_json_tree.h"

namespace oceanbase {
namespace sql {

// Newline-delimited flat objects. The CSV buffer is reused purely as a bounded
// line reader with quoting and delimiter recognition disabled.
class FileJsonReader : public IFileRowReader
{
public:
  FileJsonReader() : inferred_rows_(0), inferred_(false) {}
  virtual ~FileJsonReader() { close(); }
  int open(const ObString &path);
  int infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns) override;
  int begin_scan() override;
  int next_batch(int64_t max_rows, ObArray<ObString> &cells,
                 ObArray<uint8_t> &nulls, int64_t &rows) override;
  int rescan() override { return begin_scan(); }
  void close() override;
  int64_t column_count() const override { return columns_.count(); }
  int64_t inferred_rows() const override { return inferred_rows_; }
  ObString column_name(int64_t index) const override { return columns_.at(index).name_; }
  int signature(ObIAllocator &allocator, ObString &value) const override
  { return lines_.signature(allocator, value); }

private:
  int read_object(common::ObJsonObject *&object, bool &eof);
  int field_value(common::ObJsonNode *value, ObString &text, ObFileColumnType &type);
  int64_t find_column(const ObString &name) const;

  ObFileCsvReader lines_;
  ObArenaAllocator schema_allocator_;
  ObArenaAllocator row_allocator_;
  ObArenaAllocator batch_allocator_;
  ObArray<ObFileColumnSchema> columns_;
  int64_t inferred_rows_;
  bool inferred_;
};

} // namespace sql
} // namespace oceanbase
