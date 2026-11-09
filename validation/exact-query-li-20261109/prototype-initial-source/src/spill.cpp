#include "spill.hpp"
#include "sql.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <filesystem>
#include <limits>
#include <queue>
#include <vector>

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace mvdb {
namespace {
constexpr uint64_t header_size = 16;
constexpr size_t fan_in = 16;
constexpr size_t prefix_size = 128;
constexpr size_t copy_size = 16384;

[[noreturn]] void io_error(const char* operation) {
  throw Error("IO", std::string(operation) + ": " + std::strerror(errno));
}
[[noreturn]] void invalid_file() { throw Error("IO", "invalid external-sort record bounds"); }
uint64_t checked_add(uint64_t a, uint64_t b) {
  if (b > std::numeric_limits<uint64_t>::max() - a) invalid_file();
  return a + b;
}
void encode64(char* out, uint64_t value) {
  for (int i = 0; i < 8; ++i) out[i] = static_cast<char>(value >> (8 * i));
}
uint64_t decode64(const char* data) {
  uint64_t value = 0;
  for (int i = 0; i < 8; ++i) value |= uint64_t(static_cast<unsigned char>(data[i])) << (8 * i);
  return value;
}

// Exactly two anonymous files serve any number of runs/passes. The returned
// stream shares ownership of the final file, independently of the sorter.
class TempFile {
 public:
  explicit TempFile(const std::string& directory) {
    std::error_code ec;
    std::filesystem::create_directories(directory, ec);
    if (ec) throw Error("IO", "create sort directory: " + ec.message());
    std::string name = (std::filesystem::path(directory) / ".mvdb-sort-XXXXXX").string();
    std::vector<char> path(name.begin(), name.end()); path.push_back('\0');
    fd_ = ::mkstemp(path.data());
    if (fd_ < 0) io_error("create sort temporary file");
    if (::unlink(path.data()) != 0) {
      int saved = errno; ::close(fd_); fd_ = -1; errno = saved;
      io_error("unlink sort temporary file");
    }
    if (::fcntl(fd_, F_SETFD, FD_CLOEXEC) < 0) {
      int saved = errno; ::close(fd_); fd_ = -1; errno = saved;
      io_error("set sort descriptor close-on-exec");
    }
  }
  ~TempFile() { if (fd_ >= 0) ::close(fd_); }
  TempFile(const TempFile&) = delete;
  TempFile& operator=(const TempFile&) = delete;
  uint64_t size() const { return size_; }
  void clear() {
    if (::ftruncate(fd_, 0) != 0) io_error("truncate sort temporary file");
    size_ = 0;
  }
  void read(uint64_t offset, char* data, size_t length) const {
    if (offset > size_ || length > size_ - offset) invalid_file();
    size_t done = 0;
    while (done < length) {
      const size_t part = std::min<size_t>(length - done, 1024 * 1024);
      ssize_t n = ::pread(fd_, data + done, part, static_cast<off_t>(offset + done));
      if (n < 0) { if (errno == EINTR) continue; io_error("read sort temporary file"); }
      if (n == 0) throw Error("IO", "unexpected EOF in sort temporary file");
      done += static_cast<size_t>(n);
    }
  }
  void write(uint64_t offset, const char* data, size_t length) {
    const uint64_t end = checked_add(offset, length);
    if (end > static_cast<uint64_t>(std::numeric_limits<off_t>::max()))
      throw Error("IO", "sort temporary file exceeds offset range");
    size_t done = 0;
    while (done < length) {
      const size_t part = std::min<size_t>(length - done, 1024 * 1024);
      ssize_t n = ::pwrite(fd_, data + done, part, static_cast<off_t>(offset + done));
      if (n < 0) { if (errno == EINTR) continue; io_error("write sort temporary file"); }
      if (n == 0) throw Error("IO", "zero-length write to sort temporary file");
      done += static_cast<size_t>(n);
    }
    size_ = std::max(size_, end);
  }
  void append(const char* data, size_t length) { write(size_, data, length); }
  void header(uint64_t offset, uint64_t first, uint64_t second) {
    std::array<char, header_size> data{};
    encode64(data.data(), first); encode64(data.data() + 8, second);
    write(offset, data.data(), data.size());
  }
 private:
  int fd_ = -1;
  uint64_t size_ = 0;
};

struct Run {
  uint64_t start = 0;
  uint64_t end = 0;
  uint64_t count = 0;
};
Run read_run(const TempFile& file, uint64_t offset) {
  std::array<char, header_size> data{};
  file.read(offset, data.data(), data.size());
  Run run;
  run.start = checked_add(offset, header_size);
  run.end = checked_add(run.start, decode64(data.data()));
  run.count = decode64(data.data() + 8);
  if (run.end > file.size() || run.count > (run.end - run.start) / header_size) invalid_file();
  if ((run.count == 0) != (run.start == run.end)) invalid_file();
  return run;
}

struct Cursor {
  Run run;
  uint64_t offset = 0;
  uint64_t remaining = 0;
  uint64_t key_offset = 0, key_length = 0, row_offset = 0, row_length = 0, next_offset = 0;
  std::array<char, prefix_size> prefix{};

  Cursor(const TempFile& file, Run range) : run(range), offset(range.start), remaining(range.count) {
    if (remaining) load(file);
  }
  void load(const TempFile& file) {
    if (!remaining || offset > run.end || header_size > run.end - offset) invalid_file();
    std::array<char, header_size> data{};
    file.read(offset, data.data(), data.size());
    key_length = decode64(data.data()); row_length = decode64(data.data() + 8);
    key_offset = checked_add(offset, header_size);
    row_offset = checked_add(key_offset, key_length);
    next_offset = checked_add(row_offset, row_length);
    if (next_offset > run.end) invalid_file();
    file.read(key_offset, prefix.data(), static_cast<size_t>(std::min<uint64_t>(prefix_size, key_length)));
  }
  void advance(const TempFile& file) {
    if (!remaining) invalid_file();
    --remaining; offset = next_offset;
    if (remaining) load(file);
    else if (offset != run.end) invalid_file();
  }
};

int compare_key(const TempFile& file, const Cursor& a, const Cursor& b) {
  const uint64_t common = std::min(a.key_length, b.key_length);
  size_t initial = static_cast<size_t>(std::min<uint64_t>(common, prefix_size));
  int cmp = std::memcmp(a.prefix.data(), b.prefix.data(), initial);
  if (cmp != 0) return cmp;
  std::array<char, 4096> left{}, right{};
  for (uint64_t offset = initial; offset < common;) {
    size_t part = static_cast<size_t>(std::min<uint64_t>(left.size(), common - offset));
    file.read(a.key_offset + offset, left.data(), part);
    file.read(b.key_offset + offset, right.data(), part);
    cmp = std::memcmp(left.data(), right.data(), part);
    if (cmp != 0) return cmp;
    offset += part;
  }
  return (a.key_length > b.key_length) - (a.key_length < b.key_length);
}
void copy_range(const TempFile& src, TempFile& dest, uint64_t offset, uint64_t length) {
  std::array<char, copy_size> buffer{};
  while (length) {
    const size_t part = static_cast<size_t>(std::min<uint64_t>(buffer.size(), length));
    src.read(offset, buffer.data(), part); dest.append(buffer.data(), part);
    offset += part; length -= part;
  }
}

class FileRows final : public RowStream {
 public:
  FileRows(std::shared_ptr<TempFile> file, Run run, std::optional<uint64_t> limit)
      : file_(std::move(file)), run_(run), count_(std::min(run.count, limit.value_or(run.count))) { reset(); }
  void reset() override { next_ = run_.start; remaining_ = count_; }
  bool next(std::string& row) override {
    if (!remaining_) { row.clear(); return false; }
    if (next_ > run_.end || header_size > run_.end - next_) invalid_file();
    std::array<char, header_size> data{};
    file_->read(next_, data.data(), data.size());
    uint64_t row_offset = checked_add(checked_add(next_, header_size), decode64(data.data()));
    uint64_t row_length = decode64(data.data() + 8);
    uint64_t end = checked_add(row_offset, row_length);
    if (end > run_.end || row_length > row.max_size()) invalid_file();
    row.resize(static_cast<size_t>(row_length));
    file_->read(row_offset, row.data(), row.size());
    next_ = end; --remaining_;
    if (!remaining_ && count_ == run_.count && next_ != run_.end) invalid_file();
    return true;
  }
 private:
  std::shared_ptr<TempFile> file_;
  Run run_;
  uint64_t count_, next_ = 0, remaining_ = 0;
};

struct Record {
  std::string key, row;
  uint64_t ordinal;
};
bool record_less(const Record& a, const Record& b) {
  const size_t common = std::min(a.key.size(), b.key.size());
  int cmp = std::memcmp(a.key.data(), b.key.data(), common);
  if (cmp) return cmp < 0;
  if (a.key.size() != b.key.size()) return a.key.size() < b.key.size();
  return a.ordinal < b.ordinal;
}
}

struct SpillSorter::Impl {
  explicit Impl(const std::string& directory, size_t budget)
      : source(std::make_shared<TempFile>(directory)), destination(std::make_shared<TempFile>(directory)),
        memory_budget(std::max<size_t>(budget, 1)) {}
  std::shared_ptr<TempFile> source, destination;
  size_t memory_budget, string_bytes = 0;
  std::vector<Record> records;
  uint64_t runs = 0, ordinal = 0;
  bool finished = false;

  void flush() {
    if (records.empty()) return;
    std::sort(records.begin(), records.end(), record_less);
    const uint64_t start = source->size();
    source->header(start, 0, 0);
    for (const auto& record : records) {
      source->header(source->size(), record.key.size(), record.row.size());
      source->append(record.key.data(), record.key.size());
      source->append(record.row.data(), record.row.size());
    }
    source->header(start, source->size() - start - header_size, records.size());
    ++runs;
    std::vector<Record>().swap(records); string_bytes = 0;
  }

  void merge_pass() {
    destination->clear();
    uint64_t input = 0, produced = 0, consumed = 0;
    while (consumed < runs) {
      std::vector<Cursor> cursors;
      cursors.reserve(fan_in);
      uint64_t total = 0;
      for (size_t i = 0; i < fan_in && consumed < runs; ++i, ++consumed) {
        auto run = read_run(*source, input);
        total = checked_add(total, run.count);
        cursors.emplace_back(*source, run); input = run.end;
      }
      auto later = [&](size_t a, size_t b) {
        int cmp = compare_key(*source, cursors[a], cursors[b]);
        return cmp != 0 ? cmp > 0 : a > b;
      };
      std::priority_queue<size_t, std::vector<size_t>, decltype(later)> queue(later);
      for (size_t i = 0; i < cursors.size(); ++i) if (cursors[i].remaining) queue.push(i);
      const uint64_t output = destination->size();
      destination->header(output, 0, 0);
      uint64_t copied = 0;
      while (!queue.empty()) {
        size_t index = queue.top(); queue.pop();
        auto& cursor = cursors[index];
        copy_range(*source, *destination, cursor.offset, cursor.next_offset - cursor.offset);
        ++copied; cursor.advance(*source);
        if (cursor.remaining) queue.push(index);
      }
      if (copied != total) invalid_file();
      destination->header(output, destination->size() - output - header_size, total);
      ++produced;
    }
    if (input != source->size()) invalid_file();
    std::swap(source, destination); runs = produced;
  }
};

SpillSorter::SpillSorter(const std::string& data_dir, size_t memory_budget)
    : impl_(std::make_unique<Impl>(data_dir, memory_budget)) {}
SpillSorter::~SpillSorter() = default;

void SpillSorter::add(std::string key, std::string row) {
  auto& p = *impl_;
  if (p.finished) throw Error("STATE", "cannot add to completed sorter");
  if (p.ordinal == UINT64_MAX) throw Error("RESOURCE", "sort row count overflow");
  uint64_t new_strings = checked_add(key.capacity(), row.capacity());
  auto projected = [&]() {
    size_t capacity = p.records.capacity();
    if (p.records.size() == capacity) {
      if (capacity > p.records.max_size() / 2) throw Error("RESOURCE", "sort buffer capacity overflow");
      capacity = capacity ? capacity * 2 : 1;
    }
    return checked_add(checked_add(p.string_bytes, new_strings), uint64_t(capacity) * sizeof(Record));
  };
  if (!p.records.empty() && projected() > p.memory_budget) p.flush();
  if (p.records.size() == p.records.capacity()) p.records.reserve(p.records.capacity() ? 2 * p.records.capacity() : 1);
  p.records.push_back({std::move(key), std::move(row), p.ordinal++});
  p.string_bytes = static_cast<size_t>(checked_add(p.string_bytes, new_strings));
  if (checked_add(p.string_bytes, uint64_t(p.records.capacity()) * sizeof(Record)) >= p.memory_budget) p.flush();
}

std::shared_ptr<RowStream> SpillSorter::finish(std::optional<uint64_t> limit) {
  auto& p = *impl_;
  if (p.finished) throw Error("STATE", "sorter already completed");
  if (limit && *limit == 0) {
    std::vector<Record>().swap(p.records); p.string_bytes = 0;
    p.source->clear(); p.source->header(0, 0, 0); p.runs = 1;
  } else {
    p.flush();
    if (p.runs == 0) { p.source->header(0, 0, 0); p.runs = 1; }
    while (p.runs > 1) p.merge_pass();
  }
  Run run = read_run(*p.source, 0);
  if (run.end != p.source->size()) invalid_file();
  auto result = std::make_shared<FileRows>(p.source, run, limit);
  p.finished = true;
  p.source.reset(); p.destination.reset();
  return result;
}
}
