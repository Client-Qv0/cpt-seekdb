/* Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
#pragma once
#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include <string>

namespace oceanbase { namespace sql {
class FileCopyWriter
{
public:
  ~FileCopyWriter() { abort(); }
  int open(const ObString &path, const ObString &root, const ObCsvOptions &options);
  int field(const ObString &text, bool is_null);
  int end_row();
  int publish();
  void abort();
private:
  int bytes(const char *data, size_t length);
  FILE *file_ = nullptr;
  ObCsvOptions options_;
  std::string target_;
  std::string temporary_;
  bool first_ = true;
  bool owns_temporary_ = false;
  int directory_fd_ = -1;
};
} }
