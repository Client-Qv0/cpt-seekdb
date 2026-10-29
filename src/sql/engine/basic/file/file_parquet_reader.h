/* Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
#pragma once
#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "rust/file-reader/include/seekdb_parquet.h"

namespace oceanbase { namespace sql {
class FileParquetReader : public IFileRowReader
{
public:
  ~FileParquetReader() override { close(); }
  int open(const ObString &path);
  int project(const ObIArray<int64_t> &indices);
  int infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns) override;
  int begin_scan() override;
  int rescan() override { return begin_scan(); }
  int next_batch(int64_t max_rows, ObArray<ObString> &cells,
                 ObArray<uint8_t> &nulls, int64_t &rows) override;
  void close() override;
  int64_t column_count() const override { return columns_.count(); }
  int64_t inferred_rows() const override { return seek_parquet_rows(handle_); }
  ObString column_name(int64_t index) const override { return columns_.at(index).name_; }
  int signature(ObIAllocator &allocator, ObString &value) const override { return guard_.signature(allocator, value); }
private:
  SeekParquet *handle_ = nullptr;
  ObFileCsvReader guard_;
  ObArenaAllocator schema_allocator_{"ParquetSchema"};
  ObArenaAllocator batch_allocator_{"ParquetBatch"};
  ObArray<ObFileColumnSchema> columns_;
};
} }
