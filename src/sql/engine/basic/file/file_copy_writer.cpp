/* Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND.
 */
#define USING_LOG_PREFIX SQL_ENG
#include "sql/engine/basic/file/file_copy_writer.h"
#include "share/ob_errno.h"
#include <filesystem>
#include <fcntl.h>
#include <atomic>
#ifdef _WIN32
#include <io.h>
#else
#include <unistd.h>
#endif

namespace oceanbase { namespace sql {
using namespace common;
int FileCopyWriter::open(const ObString &path, const ObString &root, const ObCsvOptions &options)
{
  int ret = OB_SUCCESS;
  abort(); options_ = options;
  if (path.empty() || root.empty() || root.case_compare("NULL") == 0
      || MEMCHR(path.ptr(), '\0', path.length()) != nullptr
      || MEMCHR(root.ptr(), '\0', root.length()) != nullptr) {
    ret = OB_ERR_NO_PRIVILEGE;
  } else {
    std::error_code error;
    const std::filesystem::path output(std::string(path.ptr(), path.length()));
    const auto allowed = std::filesystem::canonical(std::string(root.ptr(), root.length()), error);
    if (error || !output.is_absolute() || output.filename().empty() || output.filename() == "."
        || output.filename() == "..") { ret = OB_INVALID_ARGUMENT; }
    else {
      const auto parent = std::filesystem::canonical(output.parent_path(), error);
      const auto relative = parent.lexically_relative(allowed);
      if (error || relative.empty() || relative.is_absolute() || *relative.begin() == "..") {
        ret = OB_ERR_NO_PRIVILEGE;
      } else {
        target_ = (parent / output.filename()).string();
        const auto status = std::filesystem::symlink_status(target_, error);
        if (std::filesystem::exists(status) || std::filesystem::is_symlink(status)) {
          ret = OB_FILE_ALREADY_EXIST;
        } else if (error && error != std::errc::no_such_file_or_directory) { ret = OB_IO_ERROR; }
        else {
#ifdef _WIN32
          temporary_ = (parent / ".seekdb-copy-XXXXXX").string();
          int fd = -1;
          if (_mktemp_s(temporary_.data(), temporary_.size() + 1) == 0) {
            fd = _open(temporary_.c_str(), _O_CREAT | _O_EXCL | _O_WRONLY | _O_BINARY, _S_IREAD | _S_IWRITE);
          }
          if (fd >= 0) { owns_temporary_ = true; file_ = _fdopen(fd, "wb"); if (!file_) { _close(fd); } }
#else
          // Keep all writes/publication relative to one opened directory. A
          // later replacement of a path component cannot redirect output.
          directory_fd_ = ::open(parent.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
          static std::atomic<uint64_t> sequence{0};
          int fd = -1;
          target_ = output.filename().string();
          for (int attempt = 0; directory_fd_ >= 0 && fd < 0 && attempt < 64; ++attempt) {
            temporary_ = ".seekdb-copy-" + std::to_string(getpid()) + "-"
                         + std::to_string(sequence.fetch_add(1));
            fd = openat(directory_fd_, temporary_.c_str(), O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
            if (fd < 0 && errno != EEXIST) { break; }
          }
          if (fd >= 0) { owns_temporary_ = true; file_ = fdopen(fd, "wb"); if (!file_) { ::close(fd); } }
#endif
          if (file_ == nullptr) { ret = OB_IO_ERROR; }
        }
      }
    }
  }
  if (OB_FAIL(ret)) { abort(); }
  return ret;
}

int FileCopyWriter::bytes(const char *data, size_t length)
{
  return file_ == nullptr ? OB_NOT_INIT : (length == 0 || fwrite(data, 1, length, file_) == length) ? OB_SUCCESS : OB_IO_ERROR;
}

int FileCopyWriter::field(const ObString &text, bool is_null)
{
  int ret = OB_SUCCESS;
  if (!first_) { ret = bytes(&options_.delimiter_, 1); }
  first_ = false;
  if (OB_FAIL(ret)) {
  } else if (is_null) { ret = bytes(options_.null_str_.ptr(), options_.null_str_.length()); }
  else if (OB_FAIL(bytes(&options_.quote_, 1))) {
  } else {
    int64_t start = 0;
    for (int64_t i = 0; OB_SUCC(ret) && i < text.length(); ++i) {
      if (text.ptr()[i] == options_.quote_ || text.ptr()[i] == options_.escape_) {
        if (OB_FAIL(bytes(text.ptr() + start, i - start))) {
        } else if (OB_FAIL(bytes(&options_.escape_, 1))) {
        } else { ret = bytes(text.ptr() + i, 1); }
        start = i + 1;
      }
    }
    if (OB_SUCC(ret) && text.length() > start) { ret = bytes(text.ptr() + start, text.length() - start); }
    if (OB_SUCC(ret)) { ret = bytes(&options_.quote_, 1); }
  }
  return ret;
}

int FileCopyWriter::end_row()
{
  first_ = true;
  return bytes("\n", 1);
}

int FileCopyWriter::publish()
{
  int ret = OB_SUCCESS;
  if (file_ == nullptr) { ret = OB_NOT_INIT; }
  else {
    if (fflush(file_) != 0) { ret = OB_IO_ERROR; }
    if (fclose(file_) != 0 && OB_SUCC(ret)) { ret = OB_IO_ERROR; }
    file_ = nullptr;
    if (OB_SUCC(ret)) {
      // A hard link publishes the completed file atomically and never replaces
      // an existing target, including one created concurrently after open().
#ifdef _WIN32
      std::error_code error;
      std::filesystem::create_hard_link(temporary_, target_, error);
      if (error) { ret = error == std::errc::file_exists ? OB_FILE_ALREADY_EXIST : OB_IO_ERROR; }
#else
      if (linkat(directory_fd_, temporary_.c_str(), directory_fd_, target_.c_str(), 0) != 0) {
        ret = errno == EEXIST ? OB_FILE_ALREADY_EXIST : OB_IO_ERROR;
      }
#endif
    }
  }
  abort();
  return ret;
}

void FileCopyWriter::abort()
{
  if (file_ != nullptr) { fclose(file_); file_ = nullptr; }
  if (owns_temporary_ && !temporary_.empty()) {
#ifdef _WIN32
    std::error_code error;
    std::filesystem::remove(temporary_, error);
#else
    unlinkat(directory_fd_, temporary_.c_str(), 0);
#endif
  }
#ifndef _WIN32
  if (directory_fd_ >= 0) { ::close(directory_fd_); }
#endif
  directory_fd_ = -1;
  temporary_.clear(); target_.clear(); first_ = true; owns_temporary_ = false;
}
} }
