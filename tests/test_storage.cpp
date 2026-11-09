#ifdef NDEBUG
#undef NDEBUG
#endif
#include "storage.hpp"
#include <cassert>
#include <csignal>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <sys/ptrace.h>
#include <sys/syscall.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

using mvdb::Store;
namespace fs = std::filesystem;
struct Temp {
  std::string path;
  Temp() {
    char pattern[] = "/tmp/mvdb-storage-XXXXXX";
    char *p = ::mkdtemp(pattern);
    assert(p);
    path = p;
  }
  ~Temp() { fs::remove_all(path); }
};
void put(Store &s, int64_t id, const std::string &value) {
  s.begin_statement();
  s.put("t", id, value);
  s.finish_statement();
}
std::vector<std::pair<int64_t, std::string>> all(Store &s) {
  std::vector<std::pair<int64_t, std::string>> result;
  s.scan("t", [&](int64_t id, const std::string &data) {
    result.emplace_back(id, data);
  });
  return result;
}
void basics() {
  Temp t;
  {
    Store s(t.path);
    s.begin_statement();
    s.set_metadata("t", "schema1");
    s.finish_statement();
    put(s, 1, "one");
    put(s, 2, "two");
    s.begin();
    put(s, 1, "changed");
    s.begin_statement();
    s.erase("t", 2);
    s.put("t", 3, "three");
    s.finish_statement();
    assert(s.get("t", 1) == "changed");
    assert(!s.get("t", 2));
    assert(s.get("t", 3) == "three");
    s.begin_statement();
    s.put("t", 1, "bad");
    s.set_metadata("t", "bad_schema");
    s.erase("t", 3);
    s.abort_statement();
    assert(s.get("t", 1) == "changed");
    assert(s.get("t", 3) == "three");
    assert(s.metadata("t") == "schema1");
    s.rollback();
    assert(s.get("t", 1) == "one");
    assert(s.get("t", 2) == "two");
    assert(!s.get("t", 3));
    s.begin();
    put(s, 1, "committed");
    put(s, 3, "three");
    s.commit();
    s.begin_statement();
    s.put("t", 9, "aborted-autocommit");
    s.abort_statement();
    assert(!s.get("t", 9));
    s.begin();
    put(s, 4, "shutdown-uncommitted");
  }
  {
    Store s(t.path);
    assert(s.metadata("t") == "schema1");
    assert(s.get("t", 1) == "committed");
    assert(s.get("t", 2) == "two");
    assert(s.get("t", 3) == "three");
    assert(!s.get("t", 4));
    assert(!s.get("t", 9));
    s.begin();
    s.begin_statement();
    s.set_metadata("new", "schema");
    s.finish_statement();
    s.rollback();
    assert(!s.metadata("new"));
  }
}
void snapshot_scan() {
  Temp t;
  Store s(t.path);
  for (int i = 0; i < 5; ++i)
    put(s, i, "v" + std::to_string(i));
  s.begin();
  put(s, 1, "tx");
  s.begin_statement();
  int seen = 0;
  s.scan("t", [&](int64_t id, const std::string &value) {
    assert(value == (id == 1 ? "tx" : "v" + std::to_string(id)));
    ++seen;
    s.put("t", id + 100, "new");
    s.erase("t", id);
    s.put("t", 4, "modified-mid-scan");
  });
  assert(seen == 5);
  s.finish_statement();
  s.rollback();
  assert(all(s).size() == 5);
  put(s, std::numeric_limits<int64_t>::min(), std::string("\0\x01\xff", 3));
  put(s, std::numeric_limits<int64_t>::max(), "last");
  auto r = all(s);
  assert(r.front().first == std::numeric_limits<int64_t>::min());
  assert(r.front().second == std::string("\0\x01\xff", 3));
  assert(r.back().first == std::numeric_limits<int64_t>::max());
}
void crash_recovery() {
  Temp t;
  int pipefd[2];
  assert(::pipe(pipefd) == 0);
  pid_t child = ::fork();
  assert(child >= 0);
  if (child == 0) {
    ::close(pipefd[0]);
    Store s(t.path);
    put(s, 1, "acknowledged");
    s.begin();
    put(s, 1, "uncommitted");
    put(s, 2, "uncommitted");
    char x = 'x';
    assert(::write(pipefd[1], &x, 1) == 1);
    for (;;)
      ::pause();
  }
  ::close(pipefd[1]);
  char x;
  assert(::read(pipefd[0], &x, 1) == 1);
  ::close(pipefd[0]);
  assert(::kill(child, SIGKILL) == 0);
  int status;
  assert(::waitpid(child, &status, 0) == child);
  for (int i = 0; i < 3; ++i) {
    Store s(t.path);
    assert(s.get("t", 1) == "acknowledged");
    assert(!s.get("t", 2));
  }
  {
    std::ofstream out(fs::path(t.path) / "journal.mvdb",
                      std::ios::binary | std::ios::app);
    out << "partial-frame";
  }
  {
    Store s(t.path);
    assert(s.get("t", 1) == "acknowledged");
    put(s, 3, "after-recovery");
  }
  {
    Store s(t.path);
    assert(s.get("t", 3) == "after-recovery");
  }
}
void every_truncated_commit() {
  Temp source;
  {
    Store s(source.path);
    put(s, 1, "old");
  }
  const auto journal = fs::path(source.path) / "journal.mvdb";
  const auto before = fs::file_size(journal);
  {
    Store s(source.path);
    s.begin();
    put(s, 1, "new");
    put(s, 2, "two");
    s.commit();
  }
  const auto after = fs::file_size(journal);
  for (auto cut = before; cut <= after; ++cut) {
    Temp dest;
    auto path = fs::path(dest.path) / "journal.mvdb";
    fs::copy_file(journal, path);
    fs::resize_file(path, cut);
    {
      Store s(dest.path);
      assert(s.get("t", 1) == (cut == after ? "new" : "old"));
      assert(bool(s.get("t", 2)) == (cut == after));
    }
    // Repeated recovery must produce precisely the same durable state.
    {
      Store s(dest.path);
      assert(s.get("t", 1) == (cut == after ? "new" : "old"));
    }
  }
}
void locking() {
  Temp t;
  Store s(t.path);
  bool rejected = false;
  try {
    Store other(t.path);
  } catch (const mvdb::Error &e) {
    rejected = e.code == "BUSY";
  }
  assert(rejected);
}
void interrupted_recovery() {
  Temp t;
  {
    Store s(t.path);
    s.begin();
    const std::string payload(1024 * 1024, 'x');
    for (int i = 0; i < 64; ++i)
      put(s, i, payload);
    s.commit();
  }
  for (int round = 0; round < 2; ++round) {
    pid_t child = ::fork();
    assert(child >= 0);
    if (child == 0) {
      if (::ptrace(PTRACE_TRACEME, 0, nullptr, nullptr) == -1)
        ::_exit(77);
      ::raise(SIGSTOP);
      Store s(t.path);
      ::_exit(0);
    }
    int status;
    assert(::waitpid(child, &status, 0) == child);
    if (WIFEXITED(status) && WEXITSTATUS(status) == 77) {
      std::cout << "SKIP recovery replay interruption: ptrace unavailable\n";
      return;
    }
    assert(WIFSTOPPED(status));
    if (::ptrace(PTRACE_SETOPTIONS, child, nullptr, PTRACE_O_TRACESYSGOOD) ==
        -1) {
      ::kill(child, SIGKILL);
      ::waitpid(child, &status, 0);
      std::cout
          << "SKIP recovery replay interruption: syscall tracing unavailable\n";
      return;
    }
    bool reading = false;
    for (int steps = 0; steps < 20000; ++steps) {
      assert(::ptrace(PTRACE_SYSCALL, child, nullptr, nullptr) == 0);
      assert(::waitpid(child, &status, 0) == child);
      if (WIFEXITED(status) || WIFSIGNALED(status))
        break;
      if (WSTOPSIG(status) != (SIGTRAP | 0x80))
        continue;
      struct user_regs_struct regs {};
      if (::ptrace(PTRACE_GETREGS, child, nullptr, &regs) == -1) {
        ::kill(child, SIGKILL);
        ::waitpid(child, &status, 0);
        std::cout << "SKIP recovery replay interruption: register tracing "
                     "unavailable\n";
        return;
      }
      // Linux x86_64 pread64(fd, buffer, size, offset). Crossing 1 MiB proves
      // that journal replay has begun; constructor cannot have returned yet.
      if (regs.orig_rax == SYS_pread64 && regs.r10 >= 1024 * 1024) {
        reading = true;
        break;
      }
    }
    if (!reading && !WIFEXITED(status) && !WIFSIGNALED(status)) {
      ::kill(child, SIGKILL);
      ::waitpid(child, &status, 0);
    }
    assert(reading);
    assert(::kill(child, SIGKILL) == 0);
    assert(::waitpid(child, &status, 0) == child);
  }
  Store s(t.path);
  int count = 0;
  s.scan("t", [&](int64_t id, const std::string &payload) {
    assert(id == count++);
    assert(payload.size() == 1024 * 1024);
    assert(payload.front() == 'x' && payload.back() == 'x');
  });
  assert(count == 64);
}
void checkpoint_correctness() {
  Temp t;
  const auto journal = fs::path(t.path) / "journal.mvdb";
  {
    Store s(t.path);
    s.begin_statement();
    s.set_metadata("t", "first-schema");
    s.finish_statement();
    s.begin();
    for (int id = 0; id < 64; ++id)
      put(s, id, std::string(4096, char('a' + id % 26)));
    s.commit();
    s.begin();
    for (int id = 0; id < 64; ++id) {
      s.begin_statement();
      if (id % 2 == 0)
        s.erase("t", id);
      else
        s.put("t", id, "updated:" + std::to_string(id));
      s.finish_statement();
    }
    s.begin_statement();
    s.set_metadata("t", "final-schema");
    s.finish_statement();
    s.commit();
    auto before = fs::file_size(journal);
    s.checkpoint();
    auto after = fs::file_size(journal);
    assert(after < before / 10);
    assert(!fs::exists(fs::path(t.path) / "journal.checkpoint.tmp"));
    assert(s.metadata("t") == "final-schema");
    for (int id = 0; id < 64; ++id) {
      if (id % 2 == 0)
        assert(!s.get("t", id));
      else
        assert(s.get("t", id) == "updated:" + std::to_string(id));
    }
    bool locked = false;
    try {
      Store other(t.path);
    } catch (const mvdb::Error &e) {
      locked = e.code == "BUSY";
    }
    assert(locked); // A rename must not release exclusive ownership of /data.
    s.begin();
    put(s, 1, "rollback-after-checkpoint");
    bool rejected = false;
    try {
      s.checkpoint();
    } catch (const mvdb::Error &e) {
      rejected = e.code == "TRANSACTION";
    }
    assert(rejected);
    s.rollback();
    put(s, 65, "new-after-checkpoint");
    const auto blocked = fs::path(t.path) / "journal.checkpoint.tmp";
    {
      std::ofstream out(blocked);
      out << "reserved temporary name occupied";
    }
    bool failed = false;
    try {
      s.checkpoint();
    } catch (const mvdb::Error &e) {
      failed = e.code == "IO";
    }
    assert(failed);
    assert(s.get("t", 65) == "new-after-checkpoint");
    fs::remove(blocked);
    s.checkpoint();
  }
  {
    Store s(t.path);
    assert(s.get("t", 65) == "new-after-checkpoint");
    assert(s.get("t", 1) == "updated:1");
    assert(s.metadata("t") == "final-schema");
    assert(all(s).size() == 33);
    s.begin_statement();
    s.scan("t", [&](int64_t id, const std::string &) { s.erase("t", id); });
    s.finish_statement();
    s.checkpoint();
    assert(all(s).empty());
    assert(s.metadata("t") == "final-schema");
  }
  {
    Store s(t.path);
    assert(all(s).empty());
    assert(s.metadata("t") == "final-schema");
  }
}
void automatic_checkpoint() {
  Temp t;
  const auto journal = fs::path(t.path) / "journal.mvdb";
  {
    Store s(t.path);
    for (int revision = 0; revision < 18; ++revision)
      put(s, 7, std::string(1024 * 1024, char('a' + revision)));
    assert(fs::file_size(journal) < 8 * 1024 * 1024);
    assert(s.get("t", 7)->front() == 'r');
    s.begin();
    for (int revision = 0; revision < 20; ++revision)
      put(s, 7, std::string(1024 * 1024, 'z'));
    s.rollback();
    assert(s.get("t", 7)->front() == 'r');
  }
  // Replay reconstructs the live-byte accounting used by automatic maintenance.
  {
    Store s(t.path);
    for (int revision = 0; revision < 18; ++revision)
      put(s, 7, std::string(1024 * 1024, 'x'));
    assert(fs::file_size(journal) < 8 * 1024 * 1024);
    assert(s.get("t", 7)->front() == 'x');
  }
}
void checkpoint_crash_boundaries() {
  enum Boundary {
    BeforeWrite,
    DuringWrite,
    BeforeRename,
    AfterRename,
    AfterDirectorySync
  };
  for (Boundary boundary : {BeforeWrite, DuringWrite, BeforeRename, AfterRename,
                            AfterDirectorySync}) {
    Temp t;
    {
      Store s(t.path);
      s.begin();
      s.begin_statement();
      s.set_metadata("t", "durable-schema");
      s.finish_statement();
      for (int id = 0; id < 8; ++id)
        put(s, id, std::string(1024 * 1024, char('a' + id)));
      s.commit();
      put(s, 0, "acknowledged-update");
      s.begin_statement();
      s.erase("t", 1);
      s.finish_statement();
    }
    pid_t child = ::fork();
    assert(child >= 0);
    if (child == 0) {
      Store s(t.path);
      if (::ptrace(PTRACE_TRACEME, 0, nullptr, nullptr) == -1)
        ::_exit(77);
      ::raise(SIGSTOP);
      s.checkpoint();
      ::_exit(0);
    }
    int status;
    assert(::waitpid(child, &status, 0) == child);
    if (WIFEXITED(status) && WEXITSTATUS(status) == 77) {
      std::cout << "SKIP checkpoint crash boundaries: ptrace unavailable\n";
      return;
    }
    assert(WIFSTOPPED(status));
    if (::ptrace(PTRACE_SETOPTIONS, child, nullptr, PTRACE_O_TRACESYSGOOD) ==
        -1) {
      ::kill(child, SIGKILL);
      ::waitpid(child, &status, 0);
      std::cout
          << "SKIP checkpoint crash boundaries: syscall tracing unavailable\n";
      return;
    }
    bool selected = false, entering = true;
    for (int steps = 0; steps < 20000; ++steps) {
      assert(::ptrace(PTRACE_SYSCALL, child, nullptr, nullptr) == 0);
      assert(::waitpid(child, &status, 0) == child);
      if (WIFEXITED(status) || WIFSIGNALED(status))
        break;
      if (WSTOPSIG(status) != (SIGTRAP | 0x80))
        continue;
      struct user_regs_struct regs {};
      if (::ptrace(PTRACE_GETREGS, child, nullptr, &regs) == -1) {
        ::kill(child, SIGKILL);
        ::waitpid(child, &status, 0);
        std::cout << "SKIP checkpoint crash boundaries: register tracing "
                     "unavailable\n";
        return;
      }
      selected = (boundary == BeforeWrite && entering &&
                  regs.orig_rax == SYS_pwrite64 && regs.r10 == 0) ||
                 (boundary == DuringWrite && entering &&
                  regs.orig_rax == SYS_pwrite64 && regs.r10 >= 1024 * 1024) ||
                 (boundary == BeforeRename && entering &&
                  regs.orig_rax == SYS_renameat) ||
                 (boundary == AfterRename && !entering &&
                  regs.orig_rax == SYS_renameat && regs.rax == 0) ||
                 (boundary == AfterDirectorySync && !entering &&
                  regs.orig_rax == SYS_fsync && regs.rax == 0);
      entering = !entering;
      if (selected)
        break;
    }
    if (!selected && !WIFEXITED(status) && !WIFSIGNALED(status)) {
      ::kill(child, SIGKILL);
      ::waitpid(child, &status, 0);
    }
    assert(selected);
    assert(::kill(child, SIGKILL) == 0);
    assert(::waitpid(child, &status, 0) == child);
    // Every previously acknowledged transaction must survive every maintenance
    // boundary. Old journal and new compact journal represent identical state.
    {
      Store s(t.path);
      assert(s.metadata("t") == "durable-schema");
      assert(s.get("t", 0) == "acknowledged-update");
      assert(!s.get("t", 1));
      for (int id = 2; id < 8; ++id) {
        auto value = s.get("t", id);
        assert(value && value->size() == 1024 * 1024);
        assert(value->front() == char('a' + id) &&
               value->back() == char('a' + id));
      }
      assert(!fs::exists(fs::path(t.path) / "journal.checkpoint.tmp"));
      put(s, 9, "write-after-crash");
      s.checkpoint();
    }
    {
      Store s(t.path);
      assert(s.get("t", 9) == "write-after-crash");
      assert(!s.get("t", 1));
    }
  }
}
int main() {
  basics();
  snapshot_scan();
  crash_recovery();
  every_truncated_commit();
  locking();
  interrupted_recovery();
  checkpoint_correctness();
  automatic_checkpoint();
  checkpoint_crash_boundaries();
  std::cout << "storage: 9 suites passed (including commit truncation, "
               "recovery interruption, and checkpoint crash boundaries)\n";
}
