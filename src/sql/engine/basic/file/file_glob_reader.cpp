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
#define USING_LOG_PREFIX SQL_ENG
#include "sql/engine/basic/file/file_glob_reader.h"
#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "share/ob_errno.h"
#include <algorithm>
#include <filesystem>

namespace oceanbase { namespace sql {
using namespace common;
namespace {
bool file_glob_match(const std::string &pattern, const std::string &text)
{
  // Filename expansion requires an explicit leading dot to discover hidden
  // files. Wildcards still match dots elsewhere in a filename.
  if (!text.empty() && text.front() == '.' && (pattern.empty() || pattern.front() != '.')) {
    return false;
  }
  size_t p = 0, t = 0, star = std::string::npos, retry = 0;
  while (t < text.size()) {
    if (p < pattern.size() && (pattern[p] == '?' || pattern[p] == text[t])) {
      ++p; ++t;
    } else if (p < pattern.size() && pattern[p] == '*') {
      star = p++; retry = t;
    } else if (star != std::string::npos) {
      p = star + 1; t = ++retry;
    } else {
      return false;
    }
  }
  while (p < pattern.size() && pattern[p] == '*') { ++p; }
  return p == pattern.size();
}
}

int FileGlobReader::open(const ObString &pattern, const ObString &secure_root)
{
  int ret = OB_SUCCESS;
  close();
  if (pattern.empty() || secure_root.empty() || secure_root.case_compare("NULL") == 0
      || MEMCHR(pattern.ptr(), '\0', pattern.length()) != nullptr
      || MEMCHR(secure_root.ptr(), '\0', secure_root.length()) != nullptr) {
    ret = OB_ERR_NO_PRIVILEGE;
  } else {
    const std::filesystem::path input(std::string(pattern.ptr(), pattern.length()));
    const auto parent = input.parent_path();
    std::error_code error;
    const auto root = std::filesystem::canonical(std::string(secure_root.ptr(), secure_root.length()), error);
    if (error || !input.is_absolute() || parent.string().find_first_of("*?") != std::string::npos) {
      ret = OB_INVALID_ARGUMENT;
    } else {
      const auto directory = std::filesystem::canonical(parent, error);
      const auto relative = directory.lexically_relative(root);
      if (error || relative.empty() || relative.is_absolute() || *relative.begin() == ".."
          || !std::filesystem::is_directory(directory, error)) {
        ret = OB_ERR_NO_PRIVILEGE;
      } else {
        std::filesystem::directory_iterator it(directory, error), end;
        int64_t bytes = 0;
        for (; OB_SUCC(ret) && !error && it != end; it.increment(error)) {
          const auto &entry = *it;
          if (file_glob_match(input.filename().string(), entry.path().filename().string())
              && entry.is_regular_file(error)) {
            const auto name = (parent / entry.path().filename()).string();
            const ObString file(name.size(), name.data());
            if (OB_FAIL(ObFileCsvReader::check_secure_path(file, secure_root))) {
              // Matching a symlink must never expose an out-of-scope target.
            } else if (files_.size() >= 10000 || (bytes += name.size()) > 16 * 1024 * 1024) {
              ret = OB_SIZE_OVERFLOW;
            } else {
              files_.push_back(name);
            }
          }
        }
        if (OB_SUCC(ret) && error) { ret = OB_IO_ERROR; }
      }
    }
    if (OB_SUCC(ret)) { std::sort(files_.begin(), files_.end()); }
  }
  if (OB_FAIL(ret)) { close(); }
  return ret;
}

int FileGlobReader::infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns)
{
  UNUSED(allocator);
  columns.reuse();
  ObFileColumnSchema column;
  column.name_ = column_name(0);
  column.type_ = OB_FILE_COL_VARCHAR;
  column.max_length_ = 1;
  for (const auto &name : files_) {
    column.max_length_ = MAX(column.max_length_, static_cast<int64_t>(name.size()));
  }
  return columns.push_back(column);
}

int FileGlobReader::next_batch(int64_t max_rows, ObArray<ObString> &cells,
                              ObArray<uint8_t> &nulls, int64_t &rows)
{
  int ret = max_rows > 0 ? OB_SUCCESS : OB_INVALID_ARGUMENT;
  cells.reuse(); nulls.reuse(); rows = 0;
  for (; OB_SUCC(ret) && rows < max_rows && position_ < files_.size(); ++position_) {
    const auto &name = files_[position_];
    if (OB_FAIL(cells.push_back(ObString(name.size(), name.data())))) {
    } else if (OB_FAIL(nulls.push_back(0))) {
    } else { ++rows; }
  }
  return ret;
}

int FileGlobReader::signature(ObIAllocator &allocator, ObString &value) const
{
  // Include every bounded pathname: resolution and execution must see the same set.
  std::string names;
  for (const auto &name : files_) { names.append(name); names.push_back('\0'); }
  return ob_write_string(allocator, ObString(names.size(), names.data()), value);
}
} }
