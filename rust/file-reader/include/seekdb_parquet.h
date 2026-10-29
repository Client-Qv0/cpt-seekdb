/* Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct SeekParquet SeekParquet;
// Returned slices are borrowed until the next call on the same handle.
typedef struct SeekParquetCell {
  const uint8_t *data;
  size_t length;
  uint8_t is_null;
} SeekParquetCell;
SeekParquet *seek_parquet_open(const uint8_t *path, size_t length);
void seek_parquet_close(SeekParquet *handle);
int64_t seek_parquet_columns(const SeekParquet *handle);
int64_t seek_parquet_rows(const SeekParquet *handle);
int32_t seek_parquet_column(const SeekParquet *handle, size_t index,
                           SeekParquetCell *name, int32_t *type, uint8_t *nullable);
// 0 = row, 1 = EOF, negative = decoding/resource/unsupported-type error.
int32_t seek_parquet_next(SeekParquet *handle, const SeekParquetCell **cells);
int32_t seek_parquet_rewind(SeekParquet *handle);
int32_t seek_parquet_project(SeekParquet *handle, const size_t *indices, size_t count);
#ifdef __cplusplus
}
#endif
