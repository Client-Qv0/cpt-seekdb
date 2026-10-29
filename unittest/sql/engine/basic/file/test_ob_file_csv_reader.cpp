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

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <unistd.h>
#include "sql/engine/basic/file/ob_file_csv_reader.h"
#include "sql/engine/basic/file/file_json_reader.h"
#include "sql/engine/basic/file/file_glob_reader.h"
#include "sql/engine/basic/file/file_copy_writer.h"
#include "share/ob_errno.h"

using namespace oceanbase;
using namespace oceanbase::common;
using namespace oceanbase::sql;

namespace {
class FileCsvReaderTest : public ::testing::Test
{
protected:
  std::filesystem::path dir_;
  ObArenaAllocator allocator_;
  void SetUp() override
  {
    char name[] = "/tmp/seekdb-file-scan-XXXXXX";
    ASSERT_NE(nullptr, mkdtemp(name));
    dir_ = name;
  }
  void TearDown() override
  {
    std::error_code error;
    std::filesystem::remove_all(dir_, error);
  }
  std::string write(const char *name, const char *contents)
  {
    std::string file = (dir_ / name).string();
    std::ofstream out(file, std::ios::binary);
    out << contents;
    return file;
  }
  static ObString str(const std::string &value)
  {
    return ObString(static_cast<int32_t>(value.size()), value.data());
  }
};

TEST_F(FileCsvReaderTest, infers_metadata_then_streams_and_rescans)
{
  auto path = write("rows.csv", "id,note,active\n1,alpha,true\n2,,false\n3,charlie,true\n");
  ObFileCsvReader reader;
  ObArray<ObFileColumnSchema> columns;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ASSERT_EQ(OB_SUCCESS, reader.infer_schema(allocator_, columns));
  ASSERT_EQ(3, columns.count());
  EXPECT_EQ(3, reader.inferred_rows());
  EXPECT_EQ(OB_FILE_COL_BIGINT, columns.at(0).type_);
  EXPECT_EQ(7, columns.at(1).max_length_);
  EXPECT_EQ(1, columns.at(1).null_count_);
  EXPECT_EQ(OB_FILE_COL_BOOLEAN, columns.at(2).type_);
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t count = 0;
  ASSERT_EQ(OB_SUCCESS, reader.begin_scan());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(2, cells, nulls, count));
  ASSERT_EQ(2, count);
  EXPECT_EQ(0, cells.at(0).compare("1"));
  EXPECT_EQ(1, nulls.at(4));
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(2, cells, nulls, count));
  ASSERT_EQ(1, count);
  EXPECT_EQ(0, cells.at(0).compare("3"));
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(2, cells, nulls, count));
  EXPECT_EQ(0, count);
  ASSERT_EQ(OB_SUCCESS, reader.rescan());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1, cells, nulls, count));
  EXPECT_EQ(0, cells.at(0).compare("1"));
}

TEST_F(FileCsvReaderTest, preserves_multiline_quotes_crlf_and_empty_string)
{
  auto path = write("quotes.csv", "id,note\r\n1,\"a\r\nb,\"\"c\"\"\"\r\n2,\"\"\r\n");
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(5, cells, nulls, rows));
  ASSERT_EQ(2, rows);
  EXPECT_EQ(0, cells.at(1).compare("a\r\nb,\"c\""));
  EXPECT_EQ(0, cells.at(3).length());
  EXPECT_EQ(0, nulls.at(3));
}

TEST_F(FileCsvReaderTest, rejects_partial_malformed_batches)
{
  auto path = write("bad.csv", "a,b\n1,2\n3,4,5\n");
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  EXPECT_EQ(OB_INVALID_DATA, reader.next_batch(5, cells, nulls, rows));
  EXPECT_EQ(0, rows);
  EXPECT_TRUE(cells.empty());
  EXPECT_EQ(OB_INVALID_ARGUMENT, reader.next_batch(0, cells, nulls, rows));
}

TEST_F(FileCsvReaderTest, denies_symlink_escape_and_prefix_sibling)
{
  auto permitted = write("inside.csv", "id\n1\n");
  const auto root = (dir_ / "allowed");
  std::filesystem::create_directory(root);
  std::filesystem::create_symlink(permitted, root / "escape.csv");
  const auto linked = (root / "escape.csv").string();
  EXPECT_EQ(OB_ERR_NO_PRIVILEGE, ObFileCsvReader::check_secure_path(str(linked), str(root.string())));
  EXPECT_EQ(OB_SUCCESS, ObFileCsvReader::check_secure_path(str(permitted), str(dir_.string())));
  EXPECT_EQ(OB_ERR_NO_PRIVILEGE, ObFileCsvReader::check_secure_path(str(permitted), str(root.string())));
  EXPECT_EQ(OB_ERR_NO_PRIVILEGE, ObFileCsvReader::check_secure_path(str(permitted), ObString()));
}

TEST_F(FileCsvReaderTest, detects_same_size_file_changes_between_batches)
{
  auto path = write("changing.csv", "id\n1\n2\n");
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1, cells, nulls, rows));
  auto old_time = std::filesystem::last_write_time(path);
  write("changing.csv", "id\n8\n9\n");
  std::filesystem::last_write_time(path, old_time + std::chrono::nanoseconds(1));
  EXPECT_EQ(OB_INVALID_DATA, reader.next_batch(1, cells, nulls, rows));
  EXPECT_EQ(0, rows);
}

TEST_F(FileCsvReaderTest, detects_file_replacement_even_when_size_and_time_match)
{
  auto path = write("replace.csv", "id\n1\n2\n");
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  auto replacement = write("new.csv", "id\n8\n9\n");
  std::filesystem::last_write_time(replacement, std::filesystem::last_write_time(path));
  std::filesystem::rename(replacement, path);
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  EXPECT_EQ(OB_INVALID_DATA, reader.next_batch(1, cells, nulls, rows));
}

TEST_F(FileCsvReaderTest, bounds_batch_bytes_independently_of_requested_rows)
{
  const std::string field(4 * 1024 * 1024, 'x');
  auto path = write("wide.csv", ("value\n" + field + "\n" + field + "\n" + field + "\n").c_str());
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1000, cells, nulls, rows));
  EXPECT_EQ(2, rows);
  EXPECT_EQ(4 * 1024 * 1024, cells.at(0).length());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1000, cells, nulls, rows));
  EXPECT_EQ(1, rows);
}

TEST_F(FileCsvReaderTest, jsonl_unions_fields_preserves_string_types_and_missing_nulls)
{
  auto path = write("rows.jsonl", "{\"id\":1,\"value\":\"123\"}\n"
                                 "{\"id\":2,\"flag\":true}\n"
                                 "{\"id\":3,\"value\":\"\",\"flag\":null}\n");
  FileJsonReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path)));
  ObArray<ObFileColumnSchema> columns;
  ASSERT_EQ(OB_SUCCESS, reader.infer_schema(allocator_, columns));
  ASSERT_EQ(3, columns.count());
  EXPECT_EQ(3, reader.inferred_rows());
  int64_t value_index = -1;
  int64_t flag_index = -1;
  for (int64_t i = 0; i < columns.count(); ++i) {
    if (columns.at(i).name_ == "value") {
      value_index = i;
      EXPECT_EQ(OB_FILE_COL_VARCHAR, columns.at(i).type_);
      EXPECT_EQ(1, columns.at(i).null_count_);
    } else if (columns.at(i).name_ == "flag") {
      flag_index = i;
      EXPECT_EQ(OB_FILE_COL_BOOLEAN, columns.at(i).type_);
      EXPECT_EQ(2, columns.at(i).null_count_);
    }
  }
  ASSERT_GE(value_index, 0);
  ASSERT_GE(flag_index, 0);
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.begin_scan());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(10, cells, nulls, rows));
  ASSERT_EQ(3, rows);
  EXPECT_EQ(0, cells.at(value_index).compare("123"));
  EXPECT_EQ(1, nulls.at(3 + value_index));
  EXPECT_EQ(0, nulls.at(6 + value_index));
  EXPECT_EQ(0, cells.at(6 + value_index).length());
  EXPECT_EQ(1, nulls.at(flag_index));
  ASSERT_EQ(OB_SUCCESS, reader.rescan());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1, cells, nulls, rows));
  EXPECT_EQ(0, cells.at(value_index).compare("123"));
}

TEST_F(FileCsvReaderTest, jsonl_rejects_nested_fields_and_non_object_rows)
{
  const char *cases[] = {"{\"a\":[]}\n", "{\"a\":{}}\n", "[]\n", "true\n", "not-json\n"};
  for (const char *contents : cases) {
    SCOPED_TRACE(contents);
    auto path = write("invalid.jsonl", contents);
    FileJsonReader reader;
    ObArray<ObFileColumnSchema> columns;
    ASSERT_EQ(OB_SUCCESS, reader.open(str(path)));
    EXPECT_NE(OB_SUCCESS, reader.infer_schema(allocator_, columns));
  }
}

TEST_F(FileCsvReaderTest, jsonl_widens_numbers_and_dates_from_all_rows)
{
  auto path = write("types.jsonl", "{\"number\":1,\"date\":\"2026-10-28\"}\n"
                                  "{\"number\":2.5,\"date\":\"2026-10-28 12:00:00\"}\n");
  FileJsonReader reader;
  ObArray<ObFileColumnSchema> columns;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path)));
  ASSERT_EQ(OB_SUCCESS, reader.infer_schema(allocator_, columns));
  ASSERT_EQ(2, columns.count());
  for (int64_t i = 0; i < 2; ++i) {
    EXPECT_EQ(columns.at(i).name_ == "date" ? OB_FILE_COL_DATETIME : OB_FILE_COL_DOUBLE,
              columns.at(i).type_);
  }
}
TEST_F(FileCsvReaderTest, glob_discovers_only_matching_files_and_rejects_escape)
{
  const auto first = write("first.csv", "id\n1\n");
  const auto second = write("second.csv", "id\n2\n");
  write("ignore.jsonl", "{}\n");
  FileGlobReader reader;
  const auto root = std::filesystem::path(first).parent_path().string();
  const auto pattern = root + "/*.csv";
  ASSERT_EQ(OB_SUCCESS, reader.open(str(pattern), str(root)));
  EXPECT_EQ(2, reader.inferred_rows());
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(1, cells, nulls, rows));
  ASSERT_EQ(1, rows);
  EXPECT_EQ(str(first), cells.at(0));
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(5, cells, nulls, rows));
  EXPECT_EQ(1, rows);
  EXPECT_EQ(str(second), cells.at(0));
  ASSERT_EQ(OB_SUCCESS, reader.rescan());
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(5, cells, nulls, rows));
  EXPECT_EQ(2, rows);
  EXPECT_NE(OB_SUCCESS, reader.open(str(root + "/../*.csv"), str(root)));
}
TEST_F(FileCsvReaderTest, copy_publishes_atomically_and_round_trips_null_empty_and_quoted_data)
{
  const auto marker = write("marker.txt", "");
  const auto root = std::filesystem::path(marker).parent_path().string();
  const auto path = root + "/export.csv";
  ObCsvOptions options;
  options.null_str_ = ObString::make_string("NULL");
  FileCopyWriter writer;
  ASSERT_EQ(OB_SUCCESS, writer.open(str(path), str(root), options));
  ASSERT_EQ(OB_SUCCESS, writer.field(ObString::make_string("value"), false));
  ASSERT_EQ(OB_SUCCESS, writer.end_row());
  const char *values[] = {"hello,\n\"world\"", "", "NULL"};
  for (const char *value : values) {
    ASSERT_EQ(OB_SUCCESS, writer.field(ObString::make_string(value), false));
    ASSERT_EQ(OB_SUCCESS, writer.end_row());
  }
  ASSERT_EQ(OB_SUCCESS, writer.field(ObString(), true));
  ASSERT_EQ(OB_SUCCESS, writer.end_row());
  EXPECT_FALSE(std::filesystem::exists(path));
  ASSERT_EQ(OB_SUCCESS, writer.publish());
  ObFileCsvReader reader;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), options));
  ASSERT_EQ(OB_SUCCESS, reader.begin_scan());
  ObArray<ObString> cells;
  ObArray<uint8_t> nulls;
  int64_t rows = 0;
  ASSERT_EQ(OB_SUCCESS, reader.next_batch(10, cells, nulls, rows));
  ASSERT_EQ(4, rows);
  for (int64_t i = 0; i < 3; ++i) {
    EXPECT_EQ(0, nulls.at(i));
    EXPECT_EQ(ObString::make_string(values[i]), cells.at(i));
  }
  EXPECT_EQ(1, nulls.at(3));
}

TEST_F(FileCsvReaderTest, copy_does_not_overwrite_or_leave_failed_output)
{
  const auto path = write("existing.csv", "original");
  const auto root = std::filesystem::path(path).parent_path().string();
  FileCopyWriter writer;
  ObCsvOptions options;
  EXPECT_NE(OB_SUCCESS, writer.open(str(path), str(root), options));
  const auto aborted = root + "/aborted.csv";
  ASSERT_EQ(OB_SUCCESS, writer.open(str(aborted), str(root), options));
  ASSERT_EQ(OB_SUCCESS, writer.field(ObString::make_string("partial"), false));
  writer.abort();
  EXPECT_FALSE(std::filesystem::exists(aborted));
  for (const auto &entry : std::filesystem::directory_iterator(root)) {
    EXPECT_NE(0, entry.path().filename().string().find(".seekdb-copy-"));
  }
  EXPECT_NE(OB_SUCCESS, writer.open(str(root + "/../escape.csv"), str(root), options));
}

TEST_F(FileCsvReaderTest, rejects_number_overflow_and_handles_case_insensitive_header_collisions)
{
  EXPECT_EQ(OB_FILE_COL_VARCHAR, ObFileTypeInfer::detect("1e9999", 6));
  const auto path = write("case.csv", "id,ID,id__2\n1,2,3\n");
  ObFileCsvReader reader;
  ObArray<ObFileColumnSchema> columns;
  ASSERT_EQ(OB_SUCCESS, reader.open(str(path), ObCsvOptions()));
  ASSERT_EQ(OB_SUCCESS, reader.infer_schema(allocator_, columns));
  ASSERT_EQ(3, columns.count());
  EXPECT_NE(0, columns.at(0).name_.case_compare(columns.at(1).name_));
  EXPECT_NE(0, columns.at(1).name_.case_compare(columns.at(2).name_));
}

TEST_F(FileCsvReaderTest, concurrent_copy_publish_preserves_first_complete_file)
{
  const auto marker = write("marker.txt", "");
  const auto root = std::filesystem::path(marker).parent_path().string();
  const auto path = root + "/raced.csv";
  ObCsvOptions options;
  FileCopyWriter first, second;
  ASSERT_EQ(OB_SUCCESS, first.open(str(path), str(root), options));
  ASSERT_EQ(OB_SUCCESS, second.open(str(path), str(root), options));
  ASSERT_EQ(OB_SUCCESS, first.field(ObString::make_string("first"), false));
  ASSERT_EQ(OB_SUCCESS, first.end_row());
  ASSERT_EQ(OB_SUCCESS, second.field(ObString::make_string("second"), false));
  ASSERT_EQ(OB_SUCCESS, second.end_row());
  ASSERT_EQ(OB_SUCCESS, first.publish());
  EXPECT_EQ(OB_FILE_ALREADY_EXIST, second.publish());
  std::ifstream input(path);
  std::string contents((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
  EXPECT_EQ("\"first\"\n", contents);
  for (const auto &entry : std::filesystem::directory_iterator(root)) {
    EXPECT_NE(0, entry.path().filename().string().find(".seekdb-copy-"));
  }
}
} // namespace
