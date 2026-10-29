/* Copyright (c) 2026 OceanBase.
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
#include "sql/engine/basic/file/ob_file_type_infer.h"
#include <string>
#include <vector>

namespace oceanbase { namespace sql {
// File discovery retains only bounded path metadata, never file contents.
class FileGlobReader : public IFileRowReader
{
public:
  int open(const ObString &pattern, const ObString &secure_root);
  int infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns) override;
  int begin_scan() override { position_ = 0; return common::OB_SUCCESS; }
  int rescan() override { return begin_scan(); }
  int next_batch(int64_t max_rows, ObArray<ObString> &cells,
                 ObArray<uint8_t> &nulls, int64_t &rows) override;
  void close() override { files_.clear(); position_ = 0; }
  int64_t column_count() const override { return 1; }
  int64_t inferred_rows() const override { return files_.size(); }
  ObString column_name(int64_t) const override { return ObString::make_string("file"); }
  int signature(ObIAllocator &allocator, ObString &value) const override;
private:
  std::vector<std::string> files_;
  size_t position_ = 0;
};
} }
