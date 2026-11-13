#include "storage.hpp"
#include "compact_rows.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <limits>
#include <map>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <unistd.h>

namespace mvdb {
namespace {
constexpr size_t kFileHeader = 16;
constexpr size_t kFrameHeader = 32;
constexpr uint32_t kFrameMagic = 0x3142564d;
constexpr uint32_t kMeta = 1, kPut = 2, kErase = 3, kCommit = 4;
const std::array<unsigned char, kFileHeader> kHeader = {
    'M', 'V', 'D', 'B', 'W', 'A', 'L', '1', 1, 0, 0, 0, 0, 0, 0, 0};

[[noreturn]] void io_error(const char *operation) {
  const int error = errno;
  throw Error("IO", std::string(operation) + ": " + std::strerror(error));
}
uint32_t u32(const unsigned char *p) {
  uint32_t x = 0;
  for (unsigned i = 0; i < 4; ++i)
    x |= uint32_t(p[i]) << (i * 8);
  return x;
}
uint64_t u64(const unsigned char *p) {
  uint64_t x = 0;
  for (unsigned i = 0; i < 8; ++i)
    x |= uint64_t(p[i]) << (i * 8);
  return x;
}
void set32(unsigned char *p, uint32_t v) {
  for (unsigned i = 0; i < 4; ++i)
    p[i] = static_cast<unsigned char>(v >> (i * 8));
}
void set64(unsigned char *p, uint64_t v) {
  for (unsigned i = 0; i < 8; ++i)
    p[i] = static_cast<unsigned char>(v >> (i * 8));
}
uint32_t crc_update(uint32_t crc, const void *data, size_t length) {
  static const std::array<uint32_t, 256> table = [] {
    std::array<uint32_t, 256> result{};
    for (uint32_t i = 0; i < 256; ++i) {
      uint32_t c = i;
      for (unsigned j = 0; j < 8; ++j)
        c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
      result[i] = c;
    }
    return result;
  }();
  const auto *p = static_cast<const unsigned char *>(data);
  for (size_t i = 0; i < length; ++i)
    crc = table[(crc ^ p[i]) & 255] ^ (crc >> 8);
  return crc;
}
void read_all(int fd, void *buffer, size_t size, uint64_t offset) {
  auto *p = static_cast<unsigned char *>(buffer);
  while (size) {
    const ssize_t n = ::pread(fd, p, size, static_cast<off_t>(offset));
    if (n < 0) {
      if (errno == EINTR)
        continue;
      io_error("read journal");
    }
    if (n == 0)
      throw Error("CORRUPT", "unexpected end of journal");
    p += n;
    size -= static_cast<size_t>(n);
    offset += static_cast<size_t>(n);
  }
}
void write_all(int fd, const void *buffer, size_t size, uint64_t offset) {
  const auto *p = static_cast<const unsigned char *>(buffer);
  while (size) {
    const ssize_t n = ::pwrite(fd, p, size, static_cast<off_t>(offset));
    if (n < 0) {
      if (errno == EINTR)
        continue;
      io_error("write journal");
    }
    if (n == 0)
      throw Error("IO", "zero-length write to journal");
    p += n;
    size -= static_cast<size_t>(n);
    offset += static_cast<size_t>(n);
  }
}
void write_all_dsync(int fd, const void *buffer, size_t size,
                     uint64_t offset) {
  struct iovec part{const_cast<void *>(buffer), size};
  while (part.iov_len) {
    const ssize_t written = ::pwritev2(
        fd, &part, 1, static_cast<off_t>(offset), RWF_DSYNC);
    if (written < 0) {
      if (errno == EINTR)
        continue;
      io_error("write journal");
    }
    if (written == 0)
      throw Error("IO", "zero-length write to journal");
    offset += static_cast<size_t>(written);
    if (static_cast<size_t>(written) == part.iov_len)
      return;
    part.iov_base = static_cast<unsigned char *>(part.iov_base) + written;
    part.iov_len -= static_cast<size_t>(written);
  }
}
void writev_all(int fd, struct iovec *parts, int count, uint64_t offset) {
  while (count) {
    const ssize_t written = ::pwritev(fd, parts, count,
                                      static_cast<off_t>(offset));
    if (written < 0) {
      if (errno == EINTR)
        continue;
      io_error("write journal");
    }
    if (written == 0)
      throw Error("IO", "zero-length write to journal");
    size_t consumed = static_cast<size_t>(written);
    offset += consumed;
    while (count && consumed >= parts->iov_len) {
      consumed -= parts->iov_len;
      ++parts;
      --count;
    }
    if (consumed) {
      parts->iov_base = static_cast<unsigned char *>(parts->iov_base) + consumed;
      parts->iov_len -= consumed;
    }
  }
}

void sync_fd(int fd) {
  while (::fdatasync(fd) != 0) {
    if (errno != EINTR)
      io_error("sync journal");
  }
}
} // namespace

struct Store::Impl {
  using Ref = compact::Ref;
  using Rows = compact::Rows;
  using Tables = std::map<std::string, Rows>;
  using Metadata = std::map<std::string, Ref>;
  struct Layer {
    compact::Arena &arena;
    Tables rows;
    Metadata meta;
    explicit Layer(compact::Arena &owner) : arena(owner) {}
    Rows &table_rows(const std::string &table) {
      return rows.try_emplace(table, arena).first->second;
    }
    void clear() {
      rows.clear();
      meta.clear();
    }
  };
  static constexpr size_t statement_flush_threshold = 1024 * 1024;
  std::string statement_buffer;
  uint64_t statement_buffered_start = kFileHeader;
  bool statement_previously_flushed = false;

  int fd = -1, lockfd = -1, dirfd = -1;
  uint64_t live_bytes = kFileHeader + kFrameHeader;
  uint64_t end = kFileHeader, durable_end = kFileHeader;
  uint64_t transaction_start = 0, statement_start = 0;
  bool transaction = false, statement = false, poisoned = false;
  mutable unsigned scans = 0;
  compact::Arena arena;
  Layer committed{arena}, pending{arena}, current{arena};

  explicit Impl(const std::string &directory) {
    try {
      std::filesystem::create_directories(directory);
      dirfd = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
      if (dirfd < 0)
        io_error("open data directory");
      lockfd = ::openat(dirfd, "store.lock",
                        O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
      if (lockfd < 0)
        io_error("open storage lock");
      if (::flock(lockfd, LOCK_EX | LOCK_NB) != 0)
        throw Error("BUSY", "data directory is already open");
      fd = ::openat(dirfd, "journal.mvdb",
                    O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
      if (fd < 0)
        io_error("open journal");
      if (::flock(fd, LOCK_EX | LOCK_NB) != 0)
        throw Error("BUSY", "data directory is already open");
      struct stat st {};
      if (::fstat(fd, &st) != 0)
        io_error("stat journal");
      if (!S_ISREG(st.st_mode))
        throw Error("IO", "journal must be a regular file");
      if (st.st_size < static_cast<off_t>(kFileHeader)) {
        // Interrupted creation cannot contain any acknowledged transaction.
        if (::ftruncate(fd, 0) != 0)
          io_error("initialize journal");
        write_all(fd, kHeader.data(), kHeader.size(), 0);
        sync_fd(fd);
      }
      sync_directory();
      recover();
      // A pre-rename checkpoint is never authoritative. A process may have
      // died while writing it, so only the published journal is replayed.
      if (::unlinkat(dirfd, "journal.checkpoint.tmp", 0) == 0)
        sync_directory();
      else if (errno != ENOENT)
        io_error("remove interrupted checkpoint");
    } catch (...) {
      if (fd >= 0)
        ::close(fd);
      fd = -1;
      if (lockfd >= 0)
        ::close(lockfd);
      if (dirfd >= 0)
        ::close(dirfd);
      lockfd = dirfd = -1;
      throw;
    }
  }
  ~Impl() {
    if (fd >= 0) {
      // Shutdown never commits an active statement or transaction.
      if (!poisoned && end != durable_end) {
        if (::ftruncate(fd, static_cast<off_t>(durable_end)) == 0)
          ::fdatasync(fd);
      }
      ::close(fd);
    }
    if (lockfd >= 0)
      ::close(lockfd);
    if (dirfd >= 0)
      ::close(dirfd);
  }
  void sync_directory() const {
    while (::fsync(dirfd) != 0) {
      if (errno != EINTR)
        io_error("sync data directory");
    }
  }
  void check() const {
    if (poisoned)
      throw Error("IO", "storage requires restart after an I/O failure");
  }
  void no_scan() const {
    if (scans)
      throw Error("TRANSACTION",
                  "cannot end a statement or transaction during a scan");
  }
  void require_statement() const {
    check();
    if (!statement)
      throw Error("TRANSACTION", "write requires an active statement");
  }
  static void overlay(Layer &target, Layer &source, bool remove_deleted) {
    // Node transfer avoids allocating row-index entries after durable commit.
    while (!source.rows.empty()) {
      auto ti = source.rows.begin();
      auto dst = target.rows.find(ti->first);
      if (dst == target.rows.end()) {
        if (remove_deleted) {
          for (auto i = ti->second.begin(); i != ti->second.end();) {
            if (i.ref().deleted)
              i = ti->second.erase(i);
            else
              ++i;
          }
        }
        target.rows.insert(source.rows.extract(ti));
      } else {
        auto &src_rows = ti->second;
        auto &dst_rows = dst->second;
        for (auto next = src_rows.begin(); next != src_rows.end();) {
          // Rotations and extraction preserve every other node's identity.
          // Save the successor before removing this node from the source.
          auto si = next++;
          if (remove_deleted && si.ref().deleted) {
            dst_rows.erase(si.key());
            src_rows.erase(si);
          } else {
            dst_rows.transfer(src_rows, si);
          }
        }
        source.rows.erase(ti);
      }
    }
    while (!source.meta.empty()) {
      auto si = source.meta.begin();
      auto di = target.meta.find(si->first);
      if (di == target.meta.end())
        target.meta.insert(source.meta.extract(si));
      else {
        di->second = si->second;
        source.meta.erase(si);
      }
    }
  }
  void truncate_to(uint64_t offset) {
    if (::ftruncate(fd, static_cast<off_t>(offset)) != 0) {
      poisoned = true;
      io_error("truncate journal");
    }
    end = offset;
  }
  static Ref append_to(int target_fd, uint64_t &position, uint32_t kind,
                       const std::string &table, int64_t key,
                       const std::string &value) {
    if (table.size() > 1024 * 1024 ||
        value.size() > std::numeric_limits<uint32_t>::max())
      throw Error("LIMIT", "record or table identifier is too large");
    const uint64_t bytes = kFrameHeader + table.size() + value.size();
    if (position > uint64_t(std::numeric_limits<off_t>::max()) - bytes)
      throw Error("LIMIT", "journal offset overflow");
    std::array<unsigned char, kFrameHeader> h{};
    set32(h.data(), kFrameMagic);
    set32(h.data() + 4, kind);
    set32(h.data() + 8, static_cast<uint32_t>(table.size()));
    set32(h.data() + 12, static_cast<uint32_t>(value.size()));
    uint64_t key_bits;
    std::memcpy(&key_bits, &key, sizeof key_bits);
    set64(h.data() + 16, key_bits);
    uint32_t crc = crc_update(0xffffffffu, h.data(), h.size());
    crc = crc_update(crc, table.data(), table.size());
    crc = crc_update(crc, value.data(), value.size()) ^ 0xffffffffu;
    set32(h.data() + 24, crc);
    const Ref ref{position + kFrameHeader + table.size(),
                  static_cast<uint32_t>(value.size()), kind == kErase};
    struct iovec parts[3];
    int part_count = 0;
    auto add_part = [&](const void *data, size_t size) {
      if (!size)
        return;
      parts[part_count++] = {const_cast<void *>(data), size};
    };
    add_part(h.data(), h.size());
    add_part(table.data(), table.size());
    add_part(value.data(), value.size());
    writev_all(target_fd, parts, part_count, position);

    position += bytes;
    return ref;
  }
  bool flush_statement_buffer(bool durable = false) {
    if (statement_buffer.empty()) {
      statement_buffered_start = end;
      return false;
    }
    const bool combined_sync = durable && !statement_previously_flushed;
    if (combined_sync) {
      write_all_dsync(fd, statement_buffer.data(), statement_buffer.size(),
                      statement_buffered_start);
    } else {
      write_all(fd, statement_buffer.data(), statement_buffer.size(),
                statement_buffered_start);
      statement_previously_flushed = true;
    }
    statement_buffer.clear();
    statement_buffered_start = end;
    return combined_sync;
  }
  Ref append_staged(uint32_t kind, const std::string &table, int64_t key,
                    const std::string &value) {
    if (table.size() > 1024 * 1024 ||
        value.size() > std::numeric_limits<uint32_t>::max())
      throw Error("LIMIT", "record or table identifier is too large");
    const uint64_t bytes = kFrameHeader + table.size() + value.size();
    if (end > uint64_t(std::numeric_limits<off_t>::max()) - bytes)
      throw Error("LIMIT", "journal offset overflow");
    std::array<unsigned char, kFrameHeader> h{};
    set32(h.data(), kFrameMagic);
    set32(h.data() + 4, kind);
    set32(h.data() + 8, static_cast<uint32_t>(table.size()));
    set32(h.data() + 12, static_cast<uint32_t>(value.size()));
    uint64_t key_bits;
    std::memcpy(&key_bits, &key, sizeof key_bits);
    set64(h.data() + 16, key_bits);
    uint32_t crc = crc_update(0xffffffffu, h.data(), h.size());
    crc = crc_update(crc, table.data(), table.size());
    crc = crc_update(crc, value.data(), value.size()) ^ 0xffffffffu;
    set32(h.data() + 24, crc);
    const Ref ref{end + kFrameHeader + table.size(),
                  static_cast<uint32_t>(value.size()), kind == kErase};
    statement_buffer.append(reinterpret_cast<const char *>(h.data()), h.size());
    statement_buffer.append(table);
    statement_buffer.append(value);
    end += bytes;
    if (statement_buffer.size() >= statement_flush_threshold)
      flush_statement_buffer();
    return ref;
  }

  Ref append(uint32_t kind, const std::string &table, int64_t key,
             const std::string &value) {
    check();
    try {
      return append_staged(kind, table, key, value);

    } catch (...) {
      poisoned = true;
      throw;
    }
  }
  std::string load(const Ref &ref) const {
    if (statement && ref.offset >= statement_buffered_start &&
        ref.offset <= end) {
      const uint64_t relative = ref.offset - statement_buffered_start;
      if (relative > statement_buffer.size() ||
          ref.size > statement_buffer.size() - relative)
        throw Error("CORRUPT", "buffered frame range is invalid");
      return statement_buffer.substr(static_cast<size_t>(relative), ref.size);
    }
    std::string value(ref.size, '\0');
    if (ref.size)
      read_all(fd, value.data(), value.size(), ref.offset);
    return value;
  }

  void seal(Layer &layer, bool staged = false) {
    try {
      if (staged) {
        append_staged(kCommit, {}, 0, {});
        if (!flush_statement_buffer(true))
          sync_fd(fd);
      } else {
        append_to(fd, end, kCommit, {}, 0, {});
        sync_fd(fd);
      }
      durable_end = end;
      account_live(layer);
      overlay(committed, layer, true);
    } catch (...) {
      poisoned = true;
      throw;
    }
  }

  void account_live(const Layer &incoming) {
    // Work is proportional to the current write set, never the entire database.
    for (const auto &entry : incoming.meta) {
      auto old = committed.meta.find(entry.first);
      if (old != committed.meta.end())
        live_bytes -= kFrameHeader + entry.first.size() + old->second.size;
      live_bytes += kFrameHeader + entry.first.size() + entry.second.size;
    }
    for (const auto &table : incoming.rows) {
      for (const auto &entry : table.second) {
        const auto old = find_row(committed, table.first, entry.first);
        if (old)
          live_bytes -= kFrameHeader + table.first.size() + old->size;
        if (!entry.second.deleted)
          live_bytes += kFrameHeader + table.first.size() + entry.second.size;
      }
    }
  }
  void checkpoint() {
    check();
    no_scan();
    if (transaction || statement)
      throw Error("TRANSACTION",
                  "checkpoint requires no active transaction or statement");
    int target_fd = -1;
    bool published = false;
    try {
      target_fd =
          ::openat(dirfd, "journal.checkpoint.tmp",
                   O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
      if (target_fd < 0)
        io_error("create checkpoint");
      if (::flock(target_fd, LOCK_EX | LOCK_NB) != 0)
        io_error("lock checkpoint");
      write_all(target_fd, kHeader.data(), kHeader.size(), 0);
      uint64_t position = kFileHeader;
      for (const auto &entry : committed.meta)
        append_to(target_fd, position, kMeta, entry.first, 0,
                  load(entry.second));
      for (const auto &table : committed.rows)
        for (const auto &entry : table.second)
          append_to(target_fd, position, kPut, table.first, entry.first,
                    load(entry.second));
      append_to(target_fd, position, kCommit, {}, 0, {});
      sync_fd(target_fd);
      if (::renameat(dirfd, "journal.checkpoint.tmp", dirfd, "journal.mvdb") !=
          0)
        io_error("publish checkpoint");
      published = true;
      // Nothing below allocates. The old journal remains authoritative until
      // rename; after rename the new complete journal is authoritative.
      const int old_fd = fd;
      fd = target_fd;
      target_fd = -1;
      end = durable_end = position;
      uint64_t offset = kFileHeader;
      for (auto &entry : committed.meta) {
        entry.second.offset = offset + kFrameHeader + entry.first.size();
        offset = entry.second.offset + entry.second.size;
      }
      for (auto &table : committed.rows) {
        for (auto entry = table.second.begin(); entry != table.second.end();
             ++entry) {
          auto ref = entry.ref();
          ref.offset = offset + kFrameHeader + table.first.size();
          offset = ref.offset + ref.size;
          table.second.update(entry, ref);
        }
      }
      live_bytes = position;
      ::close(old_fd);
      sync_directory();
    } catch (...) {
      if (target_fd >= 0) {
        ::close(target_fd);
        ::unlinkat(dirfd, "journal.checkpoint.tmp", 0);
      }
      // Before publication, old fd/offsets remain valid. A failure after rename
      // requires reopening so recovery can establish authoritative state.
      if (published)
        poisoned = true;
      throw;
    }
  }
  void maybe_checkpoint() {
    // Maintenance runs before a new write/transaction, never after a commit has
    // become durable but before its success response, so a maintenance failure
    // cannot report a previously committed statement as rolled back.
    constexpr uint64_t minimum_log = 16 * 1024 * 1024;
    constexpr uint64_t minimum_garbage = 8 * 1024 * 1024;
    if (end >= minimum_log && end >= live_bytes &&
        end - live_bytes >= std::max(live_bytes, minimum_garbage))
      checkpoint();
  }
  void recover() {
    std::array<unsigned char, kFileHeader> header{};
    read_all(fd, header.data(), header.size(), 0);
    if (header != kHeader)
      throw Error("CORRUPT", "unsupported journal header");
    struct stat st {};
    if (::fstat(fd, &st) != 0)
      io_error("stat journal");
    const uint64_t total = static_cast<uint64_t>(st.st_size);
    Layer replay(arena);
    uint64_t offset = kFileHeader;
    std::array<unsigned char, 64 * 1024> buffer{};
    while (total - offset >= kFrameHeader) {
      std::array<unsigned char, kFrameHeader> h{};
      read_all(fd, h.data(), h.size(), offset);
      const uint32_t kind = u32(h.data() + 4), namesize = u32(h.data() + 8),
                     size = u32(h.data() + 12);
      const uint64_t bytes = kFrameHeader + uint64_t(namesize) + uint64_t(size);
      if (u32(h.data()) != kFrameMagic || kind < kMeta || kind > kCommit ||
          u32(h.data() + 28) != 0 || namesize > 1024 * 1024 ||
          bytes > total - offset)
        break;
      if ((kind == kCommit && (namesize || size || u64(h.data() + 16))) ||
          (kind != kCommit && namesize == 0) || (kind == kErase && size != 0))
        break;
      const uint32_t expected = u32(h.data() + 24);
      set32(h.data() + 24, 0);
      uint32_t crc = crc_update(0xffffffffu, h.data(), h.size());
      uint64_t remaining = namesize + uint64_t(size),
               pos = offset + kFrameHeader;
      while (remaining) {
        size_t n =
            static_cast<size_t>(std::min<uint64_t>(remaining, buffer.size()));
        read_all(fd, buffer.data(), n, pos);
        crc = crc_update(crc, buffer.data(), n);
        pos += n;
        remaining -= n;
      }
      if ((crc ^ 0xffffffffu) != expected)
        break;
      if (kind == kCommit) {
        account_live(replay);
        overlay(committed, replay, true);
        durable_end = offset + bytes;
      } else {
        std::string table(namesize, '\0');
        read_all(fd, table.data(), table.size(), offset + kFrameHeader);
        uint64_t key_bits = u64(h.data() + 16);
        int64_t key;
        std::memcpy(&key, &key_bits, sizeof key);
        Ref ref{offset + kFrameHeader + namesize, size, kind == kErase};
        if (kind == kMeta)
          replay.meta[table] = ref;
        else
          replay.table_rows(table).set(key, ref);
      }
      offset += bytes;
    }
    // Only complete transactions become visible. Recovery is idempotent even
    // when terminated before or during this tail truncation.
    end = total;
    truncate_to(durable_end);
    if (total != durable_end)
      sync_fd(fd);
  }
  std::optional<Ref> find_row(const Layer &layer, const std::string &table,
                              int64_t key) const {
    auto t = layer.rows.find(table);
    if (t == layer.rows.end())
      return std::nullopt;
    auto r = t->second.find(key);
    return r == t->second.end() ? std::nullopt : std::optional<Ref>(r.ref());
  }
};

Store::Store(const std::string &directory)
    : impl_(std::make_unique<Impl>(directory)) {}
Store::~Store() = default;
bool Store::in_transaction() const { return impl_->transaction; }
void Store::checkpoint() { impl_->checkpoint(); }
void Store::begin() {
  auto &s = *impl_;
  s.check();
  s.no_scan();
  if (s.transaction || s.statement)
    throw Error("TRANSACTION", "transaction already active");
  s.maybe_checkpoint();
  s.transaction_start = s.end;
  s.transaction = true;
}
void Store::commit() {
  auto &s = *impl_;
  s.check();
  s.no_scan();
  if (!s.transaction || s.statement)
    throw Error("TRANSACTION", "no committable transaction");
  s.seal(s.pending);
  s.transaction = false;
}
void Store::rollback() {
  auto &s = *impl_;
  s.check();
  s.no_scan();
  if (!s.transaction || s.statement)
    throw Error("TRANSACTION", "no rollbackable transaction");
  s.truncate_to(s.transaction_start);
  s.pending.clear();
  s.transaction = false;
}
void Store::close() {
  auto &s = *impl_;
  s.check();
  s.no_scan();
  if (s.statement)
    throw Error("TRANSACTION", "cannot close during an active statement");
  if (s.transaction)
    rollback();
  // COMMIT already syncs committed data; also persist rollback truncation
  // before acknowledging shutdown, and report errors instead of swallowing
  // them in the destructor.
  if (s.fd >= 0)
    sync_fd(s.fd);
  auto close_checked = [](int &fd, const char *operation) {
    if (fd >= 0) {
      const int old = fd;
      fd = -1; // Linux releases it even on close errors; do not retry.
      if (::close(old) != 0)
        io_error(operation);
    }
  };
  close_checked(s.fd, "close journal");
  close_checked(s.lockfd, "close lock");
  close_checked(s.dirfd, "close data directory");
}
void Store::begin_statement() {
  auto &s = *impl_;
  s.check();
  s.no_scan();
  if (s.statement)
    throw Error("TRANSACTION", "statement already active");
  if (!s.transaction)
    s.maybe_checkpoint();
  s.statement_start = s.end;
  s.statement_buffer.clear();
  s.statement_buffered_start = s.end;
  s.statement_previously_flushed = false;
  s.statement = true;
}
void Store::finish_statement() {
  auto &s = *impl_;
  s.require_statement();
  s.no_scan();
  try {
    if (s.transaction) {
      s.flush_statement_buffer();
      Impl::overlay(s.pending, s.current, false);
    } else {
      s.seal(s.current, true);
    }
    s.statement = false;
    s.statement_buffer.clear();
    s.statement_buffered_start = s.end;
    s.statement_previously_flushed = false;
  } catch (...) {
    s.poisoned = true;
    throw;
  }
}
void Store::abort_statement() {
  auto &s = *impl_;
  s.no_scan();
  if (!s.statement)
    throw Error("TRANSACTION", "no active statement");
  s.statement_buffer.clear();
  if (!s.poisoned)
    s.truncate_to(s.statement_start);
  s.current.clear();
  s.statement = false;
  s.statement_buffered_start = s.end;
  s.statement_previously_flushed = false;
}
std::optional<std::string> Store::metadata(const std::string &table) const {
  const auto &s = *impl_;
  s.check();
  for (const auto *layer : {&s.current, &s.pending, &s.committed}) {
    auto it = layer->meta.find(table);
    if (it != layer->meta.end())
      return s.load(it->second);
  }
  return std::nullopt;
}
void Store::set_metadata(const std::string &table, const std::string &data) {
  auto &s = *impl_;
  s.require_statement();
  if (table.empty())
    throw Error("SCHEMA", "empty table name");
  auto ref = s.append(kMeta, table, 0, data);
  s.current.meta[table] = ref;
}
std::optional<std::string> Store::get(const std::string &table,
                                      int64_t key) const {
  const auto &s = *impl_;
  s.check();
  for (const auto *layer : {&s.current, &s.pending, &s.committed}) {
    const auto ref = s.find_row(*layer, table, key);
    if (ref)
      return ref->deleted ? std::nullopt
                          : std::optional<std::string>(s.load(*ref));
  }
  return std::nullopt;
}
void Store::put(const std::string &table, int64_t key,
                const std::string &data) {
  auto &s = *impl_;
  s.require_statement();
  if (table.empty())
    throw Error("SCHEMA", "empty table name");
  auto ref = s.append(kPut, table, key, data);
  s.current.table_rows(table).set(key, ref);
}
void Store::erase(const std::string &table, int64_t key) {
  auto &s = *impl_;
  s.require_statement();
  if (table.empty())
    throw Error("SCHEMA", "empty table name");
  auto ref = s.append(kErase, table, key, {});
  s.current.table_rows(table).set(key, ref);
}
void Store::scan(
    const std::string &table,
    const std::function<void(int64_t, const std::string &)> &fn) const {
  const auto &s = *impl_;
  s.check();
  static const Impl::Rows empty;
  auto rows = [&](const Impl::Layer &layer) -> const Impl::Rows & {
    auto it = layer.rows.find(table);
    return it == layer.rows.end() ? empty : it->second;
  };
  const auto &base = rows(s.committed);
  const auto &transaction = rows(s.pending);
  // Current statement writes may be changed by the callback. Freeze only that
  // small overlay; committed/transaction indexes remain stable during a scan.
  const Impl::Rows statement = rows(s.current);
  auto a = base.begin(), b = transaction.begin(), c = statement.begin();
  struct Guard {
    const Impl &s;
    Guard(const Impl &x) : s(x) { ++s.scans; }
    ~Guard() { --s.scans; }
  } guard(s);
  // Rows of consecutive keys usually sit back to back in the journal, so scan
  // coalesces byte-adjacent rows into one positioned read instead of issuing a
  // syscall per row. Callback order stays ascending by key.
  struct Pending {
    int64_t key;
    Impl::Ref ref;
  };
  std::vector<Pending> pending;
  pending.reserve(512);
  std::string run;
  auto in_statement_buffer = [&](const Impl::Ref &ref) {
    return s.statement && ref.offset >= s.statement_buffered_start &&
           ref.offset <= s.end;
  };
  auto slice = [&](const Pending &entry, const char *data) {
    fn(entry.key, std::string(data, entry.ref.size));
  };
  auto flush = [&] {
    size_t index = 0;
    while (index < pending.size()) {
      const Pending &first = pending[index];
      if (in_statement_buffer(first.ref)) {
        fn(first.key, s.load(first.ref));
        ++index;
        continue;
      }
      constexpr uint64_t read_limit = 1024 * 1024;
      uint64_t begin = first.ref.offset;
      uint64_t finish = begin + first.ref.size;
      size_t next = index + 1;
      // Frame headers and the table name sit between consecutive values, so a
      // run tolerates small forward gaps instead of requiring exact adjacency.
      constexpr uint64_t gap_limit = 65536;
      while (next < pending.size()) {
        const Impl::Ref &ref = pending[next].ref;
        if (in_statement_buffer(ref)) break;
        if (ref.offset < finish || ref.offset - finish > gap_limit) break;
        if (ref.offset + ref.size - begin > read_limit) break;
        finish = ref.offset + ref.size;
        ++next;
      }
      run.resize(static_cast<size_t>(finish - begin));
      if (!run.empty()) read_all(s.fd, run.data(), run.size(), begin);
      for (size_t lane = index; lane < next; ++lane)
        slice(pending[lane], run.data() + (pending[lane].ref.offset - begin));
      index = next;
    }
    pending.clear();
  };
  while (a != base.end() || b != transaction.end() || c != statement.end()) {
    int64_t key = std::numeric_limits<int64_t>::max();
    if (a != base.end())
      key = std::min(key, a.key());
    if (b != transaction.end())
      key = std::min(key, b.key());
    if (c != statement.end())
      key = std::min(key, c.key());
    Impl::Ref ref;
    if (a != base.end() && a.key() == key) {
      ref = a.ref();
      ++a;
    }
    if (b != transaction.end() && b.key() == key) {
      ref = b.ref();
      ++b;
    }
    if (c != statement.end() && c.key() == key) {
      ref = c.ref();
      ++c;
    }
    if (!ref.deleted) {
      pending.push_back({key, ref});
      if (pending.size() >= 512) flush();
    }
  }
  flush();
}
} // namespace mvdb
