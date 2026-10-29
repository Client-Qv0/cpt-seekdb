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

#define USING_LOG_PREFIX SQL_ENG

#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "share/ob_errno.h"

#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <filesystem>

#include "lib/utility/ob_print_utils.h"

namespace oceanbase
{
namespace sql
{

namespace
{
// 64bit seek, the data offset of a csv file may exceed 2GB.
int csv_fseek(FILE *fp, const int64_t offset)
{
#ifdef _WIN32
  return _fseeki64(fp, offset, SEEK_SET);
#else
  return fseeko(fp, offset, SEEK_SET);
#endif
}
} // end of anonymous namespace

ObFileCsvReader::ObFileCsvReader()
  : fp_(NULL),
    options_(),
    path_(),
    opened_(false),
    scanning_(false),
    header_loaded_(false),
    column_count_(0),
    inferred_rows_(0),
    data_start_offset_(0),
    data_offset_(0),
    meta_(),
    buf_len_(0),
    buf_start_offset_(0),
    pos_(0),
    eof_(false),
    record_no_(0),
    buf_arena_(),
    rec_buf_(&buf_arena_),
    rec_off_(),
    rec_len_(),
    rec_quoted_(),
    name_buf_(&buf_arena_),
    name_off_(),
    name_len_(),
    batch_arena_()
{
  path_buf_[0] = '\0';
  buf_[0] = '\0';
}

ObFileCsvReader::~ObFileCsvReader()
{
  close();
}

void ObFileCsvReader::close()
{
  if (OB_NOT_NULL(fp_)) {
    fclose(fp_);
    fp_ = NULL;
  }
  opened_ = false;
  scanning_ = false;
  header_loaded_ = false;
  column_count_ = 0;
  inferred_rows_ = 0;
  data_start_offset_ = 0;
  data_offset_ = 0;
  meta_.size_ = 0;
  meta_.mtime_ = 0;
  meta_.valid_ = false;
  buf_len_ = 0;
  buf_start_offset_ = 0;
  pos_ = 0;
  eof_ = false;
  record_no_ = 0;
  // the buffers are allocated from buf_arena_, release their state before the
  // arena pages are dropped.
  rec_buf_.reset();
  rec_off_.reset();
  rec_len_.reset();
  rec_quoted_.reset();
  name_buf_.reset();
  name_off_.reset();
  name_len_.reset();
  buf_arena_.reset();
  batch_arena_.reset();
  path_buf_[0] = '\0';
  path_ = ObString();
}

int ObFileCsvReader::stat_file(FileMeta &meta) const
{
  int ret = OB_SUCCESS;
  meta.size_ = 0;
  meta.mtime_ = 0;
  meta.valid_ = false;
#ifdef _WIN32
  struct _stat64 file_stat;
  if (0 != ::_stat64(path_buf_, &file_stat)) {
    ret = OB_IO_ERROR;
    LOG_WARN("fail to stat csv file", K(ret), K_(path), K(errno));
  }
#else
  struct stat file_stat;
  if (0 != ::stat(path_buf_, &file_stat)) {
    ret = OB_IO_ERROR;
    LOG_WARN("fail to stat csv file", K(ret), K_(path), K(errno));
  }
#endif
  else {
    meta.size_ = static_cast<int64_t>(file_stat.st_size);
    meta.mtime_ = static_cast<int64_t>(file_stat.st_mtime);
    meta.inode_ = file_stat.st_ino;
    meta.device_ = file_stat.st_dev;
#ifndef _WIN32
#ifdef __APPLE__
    meta.mtime_ns_ = file_stat.st_mtimespec.tv_nsec;
#else
    meta.mtime_ns_ = file_stat.st_mtim.tv_nsec;
#endif
    struct stat opened_stat;
    if (!S_ISREG(file_stat.st_mode) || (fp_ != nullptr
        && (0 != fstat(fileno(fp_), &opened_stat)
            || opened_stat.st_ino != file_stat.st_ino
            || opened_stat.st_dev != file_stat.st_dev))) {
      ret = OB_INVALID_DATA;
    }
#endif
    meta.valid_ = true;
  }
  return ret;
}

int ObFileCsvReader::signature(ObIAllocator &allocator, ObString &value) const
{
  int ret = OB_SUCCESS;
  char bytes[256];
  if (!meta_.valid_) {
    ret = OB_NOT_INIT;
  } else {
    const int length = snprintf(bytes, sizeof(bytes), "%lld:%lld:%lld:%llu:%llu",
        static_cast<long long>(meta_.size_), static_cast<long long>(meta_.mtime_),
        static_cast<long long>(meta_.mtime_ns_), static_cast<unsigned long long>(meta_.inode_),
        static_cast<unsigned long long>(meta_.device_));
    if (length < 0 || length >= sizeof(bytes)) {
      ret = OB_SIZE_OVERFLOW;
    } else {
      ret = ob_write_string(allocator, ObString(length, bytes), value);
    }
  }
  return ret;
}

int ObFileCsvReader::check_secure_path(const ObString &path, const ObString &root)
{
  int ret = OB_SUCCESS;
  if (path.empty() || root.empty() || 0 == root.case_compare("NULL")
      || MEMCHR(path.ptr(), '\0', path.length()) != nullptr
      || MEMCHR(root.ptr(), '\0', root.length()) != nullptr) {
    ret = OB_ERR_NO_PRIVILEGE;
  } else {
    std::error_code error;
    const std::filesystem::path real_root = std::filesystem::canonical(
        std::string(root.ptr(), root.length()), error);
    if (error || !std::filesystem::is_directory(real_root, error)) {
      ret = OB_ERR_NO_PRIVILEGE;
    } else {
      const std::filesystem::path real_path = std::filesystem::canonical(
          std::string(path.ptr(), path.length()), error);
      if (error || !std::filesystem::is_regular_file(real_path, error)) {
        ret = OB_INVALID_ARGUMENT;
      } else {
        const auto relative = real_path.lexically_relative(real_root);
        if (relative.empty() || relative.is_absolute() || *relative.begin() == "..") {
          ret = OB_ERR_NO_PRIVILEGE;
        }
      }
    }
  }
  return ret;
}

int ObFileCsvReader::check_unchanged() const
{
  FileMeta current;
  int ret = stat_file(current);
  if (OB_SUCC(ret) && !(current == meta_)) { ret = OB_INVALID_DATA; }
  return ret;
}

int ObFileCsvReader::open(const ObString &path, const ObCsvOptions &options, bool metadata_only)
{
  int ret = OB_SUCCESS;
  close();
  options_ = options;
  if (OB_ISNULL(path.ptr()) || path.empty()) {
    ret = OB_INVALID_ARGUMENT;
    LOG_WARN("invalid csv file path", K(ret), K(path));
  } else if (path.length() >= MAX_PATH_LENGTH
             || MEMCHR(path.ptr(), '\0', path.length()) != nullptr) {
    ret = OB_INVALID_ARGUMENT;
    LOG_WARN("csv file path is too long", K(ret), K(path), K(MAX_PATH_LENGTH));
  } else {
    MEMCPY(path_buf_, path.ptr(), path.length());
    path_buf_[path.length()] = '\0';
    path_.assign_ptr(path_buf_, static_cast<uint32_t>(path.length()));
    if (OB_ISNULL(fp_ = fopen(path_buf_, "rb"))) {
      ret = OB_FILE_NOT_EXIST;
      LOG_WARN("fail to open csv file", K(ret), K(path), K(errno));
    } else if (OB_FAIL(stat_file(meta_))) {
      LOG_WARN("fail to stat csv file", K(ret), K(path));
    } else {
      opened_ = true;
      scanning_ = false;
      header_loaded_ = false;
      column_count_ = 0;
      buf_len_ = 0;
      buf_start_offset_ = 0;
      pos_ = 0;
      eof_ = false;
      record_no_ = 0;
      // detect an UTF-8 BOM once, the scan always starts after it.
      bool has_char = false;
      char c = 0;
      if (metadata_only) {
        // Parquet uses the same descriptor identity/signature guard without
        // interpreting binary contents as CSV.
      } else if (OB_FAIL(peek(0, has_char, c))) {
        LOG_WARN("fail to read csv file", K(ret), K(path));
      } else {
        bool has_bom = false;
        if (buf_len_ >= 3) {
          has_bom = (static_cast<unsigned char>(buf_[0]) == 0xEF
                     && static_cast<unsigned char>(buf_[1]) == 0xBB
                     && static_cast<unsigned char>(buf_[2]) == 0xBF);
        }
        data_start_offset_ = has_bom ? 3 : 0;
        if (OB_FAIL(seek_to(data_start_offset_))) {
          LOG_WARN("fail to seek csv file", K(ret), K(path));
        } else {
          // best effort: parse the header eagerly so that column_count() and
          // column_index() are usable right after open().  A malformed file is
          // reported later by infer_schema() / begin_scan() / next_batch().
          const int header_ret = load_header();
          if (OB_SUCCESS != header_ret) {
            LOG_TRACE("csv header is not ready after open", K(header_ret), K_(path));
          }
        }
      }
    }
    if (OB_FAIL(ret)) {
      close();
    }
  }
  return ret;
}

int ObFileCsvReader::seek_to(const int64_t offset)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(fp_)) {
    ret = OB_NOT_INIT;
    LOG_WARN("csv reader is not opened", K(ret));
  } else if (0 != csv_fseek(fp_, offset)) {
    ret = OB_IO_ERROR;
    LOG_WARN("fail to seek csv file", K(ret), K(offset), K(errno));
  } else {
    buf_len_ = 0;
    buf_start_offset_ = offset;
    pos_ = 0;
    eof_ = false;
    record_no_ = 0;
  }
  return ret;
}

int ObFileCsvReader::fill_more()
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(fp_)) {
    ret = OB_NOT_INIT;
    LOG_WARN("csv reader is not opened", K(ret));
  } else if (eof_) {
    // keep the buffered bytes, eof only means the file has been fully read.
  } else {
    if (pos_ >= buf_len_) {
      // the whole buffer has been consumed, the next read starts after it.
      buf_start_offset_ += buf_len_;
      pos_ = 0;
      buf_len_ = 0;
    } else if (pos_ > 0) {
      // keep the unconsumed bytes at the front of the buffer.
      const int64_t remain = buf_len_ - pos_;
      MEMMOVE(buf_, buf_ + pos_, remain);
      buf_start_offset_ += pos_;
      pos_ = 0;
      buf_len_ = remain;
    }
    const int64_t space = READ_BUFFER_SIZE - buf_len_;
    if (space > 0) {
      const int64_t read_size = static_cast<int64_t>(fread(buf_ + buf_len_, 1, space, fp_));
      if (read_size > 0) {
        buf_len_ += read_size;
      } else if (0 != ferror(fp_)) {
        ret = OB_IO_ERROR;
        LOG_WARN("fail to read csv file", K(ret), K(buf_start_offset_), K(errno));
      } else {
        eof_ = true;
      }
    }
  }
  return ret;
}

int ObFileCsvReader::peek(const int64_t ahead, bool &has_char, char &c)
{
  int ret = OB_SUCCESS;
  while (OB_SUCC(ret) && !eof_ && (buf_len_ - pos_) <= ahead) {
    const int64_t before = buf_len_ - pos_;
    if (OB_FAIL(fill_more())) {
      LOG_WARN("fail to fill csv buffer", K(ret));
    } else if (eof_ || (buf_len_ - pos_) == before) {
      break;
    }
  }
  has_char = (pos_ + ahead) < buf_len_;
  if (has_char) {
    c = buf_[pos_ + ahead];
  }
  return ret;
}

int ObFileCsvReader::append_field_char(const char c)
{
  // Bound memory even for a single row with thousands of wide fields.
  return rec_buf_.length() >= 32 * 1024 * 1024 ? OB_SIZE_OVERFLOW : rec_buf_.append(&c, 1);
}

// One field.  A field starts in "unquoted" mode unless its very first char is
// the quote char; inside a quoted field the delimiter, CR / LF and the escape
// sequences are all content.
int ObFileCsvReader::parse_field(const int64_t field_start, bool &quoted, bool &record_end)
{
  int ret = OB_SUCCESS;
  quoted = false;
  record_end = false;
  bool at_field_start = true;
  bool in_quotes = false;
  bool done = false;
  while (OB_SUCC(ret) && !done) {
    bool has_char = false;
    char c = 0;
    if (OB_FAIL(peek(0, has_char, c))) {
      LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
    } else if ((static_cast<int64_t>(rec_buf_.length()) - field_start)
               > options_.max_field_len_) {
      ret = OB_SIZE_OVERFLOW;
      LOG_WARN("csv field is too long", K(ret), K(record_no_), K(options_.max_field_len_));
    } else if (!has_char) {
      // end of file also ends the current field / record.
      if (in_quotes) {
        ret = OB_INVALID_DATA;
        LOG_USER_ERROR(OB_INVALID_ARGUMENT, "CSV: unterminated quoted field");
      } else {
        record_end = true;
        done = true;
      }
    } else if (at_field_start && c == options_.quote_) {
      quoted = true;
      in_quotes = true;
      at_field_start = false;
      ++pos_;
    } else {
      at_field_start = false;
      if (in_quotes) {
        if (options_.escape_ != options_.quote_ && c == options_.escape_) {
          // backslash style escape: the next char is taken literally.
          bool has_next = false;
          char next_c = 0;
          ++pos_;
          if (OB_FAIL(peek(0, has_next, next_c))) {
            LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
          } else if (has_next) {
            if (OB_FAIL(append_field_char(next_c))) {
              LOG_WARN("fail to append csv field", K(ret), K(record_no_));
            } else {
              ++pos_;
            }
          }
        } else if (c == options_.quote_) {
          // a doubled quote is an escaped quote, otherwise this is the closing
          // quote of the field.
          bool has_next = false;
          char next_c = 0;
          if (OB_FAIL(peek(1, has_next, next_c))) {
            LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
          } else if (options_.escape_ == options_.quote_ && has_next && next_c == options_.quote_) {
            if (OB_FAIL(append_field_char(options_.quote_))) {
              LOG_WARN("fail to append csv field", K(ret), K(record_no_));
            } else {
              pos_ += 2;
            }
          } else {
            ++pos_;
            in_quotes = false;
          }
        } else if ('\r' == c) {
          // Inside a quoted field a CRLF pair is part of the value.  Normalize
          // it to a single LF so that the same logical value is produced for
          // LF and CRLF files instead of leaking the '\r' into the data.
          bool has_next = false;
          char next_c = 0;
          if (OB_FAIL(peek(1, has_next, next_c))) {
            LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
          } else if (has_next && '\n' == next_c) {
            ++pos_;
          } else if (OB_FAIL(append_field_char(c))) {
            LOG_WARN("fail to append csv field", K(ret), K(record_no_));
          } else {
            ++pos_;
          }
        } else {
          if (OB_FAIL(append_field_char(c))) {
            LOG_WARN("fail to append csv field", K(ret), K(record_no_));
          } else {
            ++pos_;
          }
        }
      } else if (c == options_.delimiter_) {
        ++pos_;
        done = true;
      } else if ('\n' == c) {
        ++pos_;
        record_end = true;
        done = true;
      } else if ('\r' == c) {
        // LF and CRLF are both accepted, a lone CR also ends the record.
        bool has_next = false;
        char next_c = 0;
        ++pos_;
        if (OB_FAIL(peek(0, has_next, next_c))) {
          LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
        } else {
          if (has_next && '\n' == next_c) {
            ++pos_;
          }
          record_end = true;
          done = true;
        }
      } else {
        if (quoted) {
          ret = OB_INVALID_DATA;
          LOG_USER_ERROR(OB_INVALID_ARGUMENT, "CSV: unexpected byte after closing quote");
        } else if (OB_FAIL(append_field_char(c))) {
          LOG_WARN("fail to append csv field", K(ret), K(record_no_));
        } else {
          ++pos_;
        }
      }
    }
  }
  return ret;
}

int ObFileCsvReader::read_record(bool &eof, bool &blank)
{
  int ret = OB_SUCCESS;
  eof = false;
  blank = false;
  rec_buf_.reuse();
  rec_off_.reuse();
  rec_len_.reuse();
  rec_quoted_.reuse();
  bool has_char = false;
  char c = 0;
  if (OB_FAIL(peek(0, has_char, c))) {
    LOG_WARN("fail to peek csv char", K(ret), K(record_no_));
  } else if (!has_char) {
    eof = true;
  } else {
    bool record_end = false;
    while (OB_SUCC(ret) && !record_end) {
      const int64_t field_start = static_cast<int64_t>(rec_buf_.length());
      bool quoted = false;
      if (OB_FAIL(parse_field(field_start, quoted, record_end))) {
        LOG_WARN("fail to parse csv field", K(ret), K(record_no_));
      } else if (rec_off_.count() >= 4096) {
        ret = OB_SIZE_OVERFLOW;
      } else if (OB_FAIL(rec_off_.push_back(field_start))) {
        LOG_WARN("fail to push csv field offset", K(ret));
      } else if (OB_FAIL(rec_len_.push_back(static_cast<int64_t>(rec_buf_.length())
                                            - field_start))) {
        LOG_WARN("fail to push csv field length", K(ret));
      } else if (OB_FAIL(rec_quoted_.push_back(quoted ? 1 : 0))) {
        LOG_WARN("fail to push csv field quoted flag", K(ret));
      }
    }
    if (OB_SUCC(ret)) {
      ++record_no_;
      // an empty line, it has a single empty unquoted field.
      blank = (1 == rec_off_.count() && 0 == rec_len_.at(0) && 0 == rec_quoted_.at(0));
    }
  }
  return ret;
}

bool ObFileCsvReader::is_null_field(const int64_t field_off, const int64_t field_len,
                                    const bool quoted) const
{
  bool is_null = false;
  if (quoted) {
    // a quoted empty field is an empty string, never NULL.
    is_null = false;
  } else if (0 == field_len) {
    is_null = true;
  } else if (!options_.null_str_.empty()
             && field_len == static_cast<int64_t>(options_.null_str_.length())
             && 0 == MEMCMP(rec_buf_.ptr() + field_off, options_.null_str_.ptr(), field_len)) {
    is_null = true;
  }
  return is_null;
}

ObString ObFileCsvReader::get_column_name(const int64_t index) const
{
  ObString name;
  if (index >= 0 && index < name_off_.count()) {
    name.assign_ptr(name_buf_.ptr() + name_off_.at(index),
                    static_cast<uint32_t>(name_len_.at(index)));
  }
  return name;
}

// append the (deduplicated) column name, a repeated name gets a __2 / __3
// suffix, an empty header cell falls back to c{N}.
int ObFileCsvReader::append_column_name(const int64_t field_off, const int64_t field_len,
                                        const int64_t index)
{
  int ret = OB_SUCCESS;
  ObStringBuffer base_name(&buf_arena_);
  ObStringBuffer candidate(&buf_arena_);
  if (0 == field_len) {
    char num_buf[32];
    int64_t num_pos = 0;
    if (OB_FAIL(databuff_printf(num_buf, sizeof(num_buf), num_pos, "c%d",
                                static_cast<int>(index + 1)))) {
      LOG_WARN("fail to format column name", K(ret), K(index));
    } else if (OB_FAIL(base_name.append(num_buf, num_pos))) {
      LOG_WARN("fail to build column name", K(ret), K(index));
    }
  } else if (OB_FAIL(base_name.append(rec_buf_.ptr() + field_off, field_len))) {
    LOG_WARN("fail to build column name", K(ret), K(index));
  }
  bool done = false;
  for (int64_t suffix = 1; OB_SUCC(ret) && !done; ++suffix) {
    candidate.reuse();
    if (1 == suffix) {
      if (OB_FAIL(candidate.append(base_name.ptr(), base_name.length()))) {
        LOG_WARN("fail to build column name", K(ret), K(index));
      }
    } else {
      char suffix_buf[32];
      int64_t suffix_pos = 0;
      if (OB_FAIL(databuff_printf(suffix_buf, sizeof(suffix_buf), suffix_pos, "__%d",
                                  static_cast<int>(suffix)))) {
        LOG_WARN("fail to format column suffix", K(ret), K(suffix));
      } else if (OB_FAIL(candidate.append(base_name.ptr(), base_name.length()))) {
        LOG_WARN("fail to build column name", K(ret), K(index));
      } else if (OB_FAIL(candidate.append(suffix_buf, suffix_pos))) {
        LOG_WARN("fail to build column name", K(ret), K(index));
      }
    }
    if (OB_FAIL(ret)) {
    } else {
      bool duplicated = false;
      for (int64_t i = 0; !duplicated && i < name_off_.count(); ++i) {
        const int64_t cur_len = name_len_.at(i);
        if (0 == ObString(cur_len, name_buf_.ptr() + name_off_.at(i)).case_compare(
                        ObString(candidate.length(), candidate.ptr()))) {
          duplicated = true;
        }
      }
      if (!duplicated) {
        done = true;
        if (OB_FAIL(name_off_.push_back(static_cast<int64_t>(name_buf_.length())))) {
          LOG_WARN("fail to push column name offset", K(ret));
        } else if (OB_FAIL(name_buf_.append(candidate.ptr(), candidate.length()))) {
          LOG_WARN("fail to push column name", K(ret));
        } else if (OB_FAIL(name_len_.push_back(static_cast<int64_t>(candidate.length())))) {
          LOG_WARN("fail to push column name length", K(ret));
        }
      }
    }
  }
  return ret;
}

int ObFileCsvReader::load_header()
{
  int ret = OB_SUCCESS;
  if (header_loaded_) {
    // nothing to do
  } else if (OB_FAIL(seek_to(data_start_offset_))) {
    LOG_WARN("fail to seek csv file", K(ret), K_(data_start_offset));
  } else {
    name_buf_.reuse();
    name_off_.reuse();
    name_len_.reuse();
    column_count_ = 0;
    bool eof = false;
    bool blank = false;
    if (OB_FAIL(read_record(eof, blank))) {
      LOG_WARN("fail to read csv header", K(ret));
    } else if (eof) {
      ret = OB_INVALID_DATA;
      LOG_WARN("csv file has no header row", K(ret), K_(path));
    } else if (rec_off_.count() <= 0) {
      ret = OB_INVALID_DATA;
      LOG_WARN("csv file has no column", K(ret), K_(path));
    } else {
      column_count_ = rec_off_.count();
      for (int64_t i = 0; OB_SUCC(ret) && i < column_count_; ++i) {
        // without a header the column names are always c1..cN, the first row
        // only decides the column count.
        const int64_t name_len = options_.header_ ? rec_len_.at(i) : 0;
        if (OB_FAIL(append_column_name(rec_off_.at(i), name_len, i))) {
          LOG_WARN("fail to build column name", K(ret), K(i));
        }
      }
      if (OB_SUCC(ret)) {
        header_loaded_ = true;
        if (options_.header_) {
          data_offset_ = buf_start_offset_ + pos_;
        } else {
          // the first row is data, the scan starts from the very beginning.
          data_offset_ = data_start_offset_;
        }
      }
    }
  }
  return ret;
}

int ObFileCsvReader::begin_scan()
{
  int ret = OB_SUCCESS;
  if (!opened_ || OB_ISNULL(fp_)) {
    ret = OB_NOT_INIT;
    LOG_WARN("csv reader is not opened", K(ret));
  } else if (OB_FAIL(load_header())) {
    LOG_WARN("fail to load csv header", K(ret));
  } else if (OB_FAIL(seek_to(data_offset_))) {
    LOG_WARN("fail to seek csv data", K(ret), K_(data_offset));
  } else {
    scanning_ = true;
  }
  return ret;
}

int ObFileCsvReader::rescan()
{
  return begin_scan();
}

int ObFileCsvReader::emit_row(ObArray<ObString> &cells, ObArray<uint8_t> &nulls)
{
  int ret = OB_SUCCESS;
  const int64_t total_len = static_cast<int64_t>(rec_buf_.length());
  char *row_base = static_cast<char *>(batch_arena_.alloc(total_len > 0 ? total_len : 1));
  if (OB_ISNULL(row_base)) {
    ret = OB_ALLOCATE_MEMORY_FAILED;
    LOG_WARN("fail to allocate csv row buffer", K(ret), K(total_len));
  } else {
    if (total_len > 0) {
      MEMCPY(row_base, rec_buf_.ptr(), total_len);
    }
    for (int64_t i = 0; OB_SUCC(ret) && i < rec_off_.count(); ++i) {
      const int64_t field_off = rec_off_.at(i);
      const int64_t field_len = rec_len_.at(i);
      const bool quoted = (1 == rec_quoted_.at(i));
      ObString cell;
      uint8_t cell_null = 0;
      if (is_null_field(field_off, field_len, quoted)) {
        cell_null = 1;
        cell.assign_ptr(row_base, 0);
      } else {
        cell.assign_ptr(row_base + field_off, static_cast<uint32_t>(field_len));
      }
      if (OB_FAIL(cells.push_back(cell))) {
        LOG_WARN("fail to push csv cell", K(ret), K(i));
      } else if (OB_FAIL(nulls.push_back(cell_null))) {
        LOG_WARN("fail to push csv null flag", K(ret), K(i));
      }
    }
  }
  return ret;
}

int ObFileCsvReader::next_batch(const int64_t max_rows, ObArray<ObString> &cells,
                                ObArray<uint8_t> &nulls, int64_t &row_count)
{
  int ret = OB_SUCCESS;
  row_count = 0;
  cells.reuse();
  nulls.reuse();
  if (max_rows <= 0) {
    ret = OB_INVALID_ARGUMENT;
  } else if (!opened_ || OB_ISNULL(fp_)) {
    ret = OB_NOT_INIT;
    LOG_WARN("csv reader is not opened", K(ret));
  } else if (OB_FAIL(load_header())) {
    LOG_WARN("fail to load csv header", K(ret));
  } else if (!scanning_ && OB_FAIL(begin_scan())) {
    LOG_WARN("fail to begin csv scan", K(ret));
  } else {
    FileMeta cur_meta;
    if (OB_FAIL(stat_file(cur_meta))) {
      LOG_WARN("fail to stat csv file", K(ret), K_(path));
    } else if (!(cur_meta == meta_)) {
      ret = OB_INVALID_DATA;
      LOG_WARN("csv file changed during scanning", K(ret), K_(path),
               "expected_size", meta_.size_, "current_size", cur_meta.size_,
               "expected_mtime", meta_.mtime_, "current_mtime", cur_meta.mtime_);
    } else {
      // the header row is the first physical line of the file.
      const int64_t line_base = options_.header_ ? 1 : 0;
      batch_arena_.reset();
      bool eof = false;
      int64_t batch_bytes = 0;
      while (OB_SUCC(ret) && !eof && row_count < max_rows && batch_bytes < 8 * 1024 * 1024) {
        bool blank = false;
        if (OB_FAIL(read_record(eof, blank))) {
          LOG_WARN("fail to read csv record", K(ret), K(record_no_));
        } else if (eof) {
          // done
        } else if (blank && column_count_ > 1) {
          // skip empty lines, they are not rows of a multi column file.
        } else if (rec_off_.count() != column_count_) {
          ret = OB_INVALID_DATA;
          LOG_WARN("csv column count mismatch", K(ret), "line_no", record_no_ + line_base,
                   "expected", column_count_, "actual", rec_off_.count(), K_(path));
        } else if (OB_FAIL(emit_row(cells, nulls))) {
          LOG_WARN("fail to emit csv row", K(ret), "line_no", record_no_ + line_base);
        } else {
          ++row_count;
          batch_bytes += rec_buf_.length();
        }
      }
      if (OB_SUCC(ret)) {
        if (OB_FAIL(stat_file(cur_meta))) {
        } else if (!(cur_meta == meta_)) {
          ret = OB_INVALID_DATA;
        }
      }
    }
  }
  if (OB_FAIL(ret)) {
    // a failed batch is not usable, do not leak a half filled batch.
    row_count = 0;
    cells.reuse();
    nulls.reuse();
  }
  return ret;
}

int ObFileCsvReader::infer_schema(ObIAllocator &allocator, ObArray<ObFileColumnSchema> &columns)
{
  int ret = OB_SUCCESS;
  inferred_rows_ = 0;
  columns.reuse();
  if (!opened_ || OB_ISNULL(fp_)) {
    ret = OB_NOT_INIT;
    LOG_WARN("csv reader is not opened", K(ret));
  } else if (OB_FAIL(load_header())) {
    LOG_WARN("fail to load csv header", K(ret));
  } else if (column_count_ <= 0) {
    ret = OB_INVALID_DATA;
    LOG_WARN("csv file has no column", K(ret), K_(path));
  } else if (OB_FAIL(seek_to(data_offset_))) {
    LOG_WARN("fail to seek csv data", K(ret), K_(data_offset));
  } else {
    ObArray<ObFileColumnType> types;
    ObArray<uint8_t> nullable;
    ObArray<int64_t> lengths;
    ObArray<int64_t> null_counts;
    for (int64_t i = 0; OB_SUCC(ret) && i < column_count_; ++i) {
      if (OB_FAIL(types.push_back(OB_FILE_COL_NULL))) {
        LOG_WARN("fail to init column type", K(ret), K(i));
      } else if (OB_FAIL(nullable.push_back(0))) {
        LOG_WARN("fail to init column nullable flag", K(ret), K(i));
      } else if (OB_FAIL(lengths.push_back(0))) {
      } else if (OB_FAIL(null_counts.push_back(0))) {
      }
    }
    bool eof = false;
    const int64_t line_base = options_.header_ ? 1 : 0;
    while (OB_SUCC(ret) && !eof) {
      bool blank = false;
      if (OB_FAIL(read_record(eof, blank))) {
        LOG_WARN("fail to read csv record", K(ret), K(record_no_));
      } else if (eof) {
        // done
      } else if (blank && column_count_ > 1) {
        // skip empty lines
      } else if (rec_off_.count() != column_count_) {
        ret = OB_INVALID_DATA;
        LOG_WARN("csv column count mismatch", K(ret), "line_no", record_no_ + line_base,
                 "expected", column_count_, "actual", rec_off_.count(), K_(path));
      } else {
        ++inferred_rows_;
        for (int64_t i = 0; OB_SUCC(ret) && i < column_count_; ++i) {
          const int64_t field_off = rec_off_.at(i);
          const int64_t field_len = rec_len_.at(i);
          lengths.at(i) = MAX(lengths.at(i), field_len);
          const bool quoted = (1 == rec_quoted_.at(i));
          ObFileColumnType cur_type = OB_FILE_COL_NULL;
          if (is_null_field(field_off, field_len, quoted)) {
            nullable.at(i) = 1;
            ++null_counts.at(i);
          } else {
            cur_type = ObFileTypeInfer::detect(rec_buf_.ptr() + field_off, field_len);
            if (quoted && OB_FILE_COL_NULL == cur_type) {
              // a quoted blank is an empty string, not NULL.
              cur_type = OB_FILE_COL_VARCHAR;
            }
          }
          types.at(i) = ObFileTypeInfer::merge(types.at(i), cur_type);
        }
      }
    }
    for (int64_t i = 0; OB_SUCC(ret) && i < column_count_; ++i) {
      ObFileColumnSchema column;
      column.type_ = types.at(i);
      column.max_length_ = lengths.at(i);
      column.null_count_ = null_counts.at(i);
      column.nullable_ = (0 != nullable.at(i)) || (OB_FILE_COL_NULL == column.type_);
      if (OB_FAIL(ob_write_string(allocator, get_column_name(i), column.name_))) {
        LOG_WARN("fail to copy column name", K(ret), K(i));
      } else if (OB_FAIL(columns.push_back(column))) {
        LOG_WARN("fail to push column schema", K(ret), K(i));
      }
    }
  }
  if (OB_SUCC(ret)) {
    FileMeta current;
    if (OB_FAIL(stat_file(current))) {
    } else if (!(current == meta_)) {
      ret = OB_INVALID_DATA;
    }
  }
  return ret;
}

int ObFileCsvReader::column_index(const ObString &name, int64_t &index) const
{
  int ret = OB_ENTRY_NOT_EXIST;
  index = -1;
  for (int64_t i = 0; OB_ENTRY_NOT_EXIST == ret && i < column_count_; ++i) {
    const ObString cur_name = get_column_name(i);
    if (cur_name.length() == name.length()
        && (0 == name.length()
            || 0 == MEMCMP(cur_name.ptr(), name.ptr(), name.length()))) {
      index = i;
      ret = OB_SUCCESS;
    }
  }
  return ret;
}

} // end namespace sql
} // end namespace oceanbase
