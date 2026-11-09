#include "spill.hpp"
#include "sql.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {
int checks = 0;
void check(bool condition, const std::string& message) {
  ++checks;
  if (!condition) throw std::runtime_error(message);
}
struct Record { std::string key, row; };
bool key_less(const Record& a, const Record& b) {
  int cmp = std::memcmp(a.key.data(), b.key.data(), std::min(a.key.size(), b.key.size()));
  return cmp ? cmp < 0 : a.key.size() < b.key.size();
}
size_t fd_count() {
  size_t n = 0;
  for (const auto& unused : std::filesystem::directory_iterator("/proc/self/fd")) { (void)unused; ++n; }
  return n;
}
void verify(mvdb::RowStream& stream, const std::vector<Record>& expected, size_t limit) {
  for (int pass = 0; pass < 2; ++pass) {
    stream.reset();
    size_t pos = 0;
    std::string row;
    while (stream.next(row)) {
      check(pos < limit && pos < expected.size(), "Stream produced too many rows");
      check(row == expected[pos].row, "Sort order or stable tie mismatch at row " + std::to_string(pos));
      ++pos;
    }
    check(pos == std::min(limit, expected.size()), "Stream row count mismatch");
    check(!stream.next(row), "Stream EOF must be repeatable");
  }
}
}

int main() {
  namespace fs = std::filesystem;
  const auto directory = fs::temp_directory_path() / ("mvdb-spill-" + std::to_string(::getpid()) + "-" +
      std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
  fs::create_directories(directory);
  try {
    std::vector<Record> records;
    std::mt19937 rng(20261109);
    for (int i = 0; i < 1200; ++i) {
      std::string key;
      const auto length = rng() % 12;
      for (unsigned j = 0; j < length; ++j) key.push_back(static_cast<char>(rng() % 256));
      records.push_back({std::move(key), "[" + std::to_string(i) + "]"});
    }
    records.push_back({std::string("\0\xff\0",3), "[1200]"});
    records.push_back({std::string("\0\xff",2), "[1201]"});
    records.push_back({std::string(8192,'q') + 'a', "[1202]"});
    records.push_back({std::string(8192,'q') + 'b', "[1203]"});
    records.push_back({std::string(8192,'q') + 'a', "[1204]"});
    records.push_back({"huge-row", "[\"" + std::string(131072,'x') + "\"]"});
    auto expected = records;
    std::stable_sort(expected.begin(), expected.end(), key_less);
    const size_t before = fd_count();
    std::shared_ptr<mvdb::RowStream> stream;
    {
      mvdb::SpillSorter sorter(directory.string(),1);
      for (const auto& r : records) sorter.add(r.key,r.row);
      check(fd_count() <= before + 2,"Each run must not retain a separate fd");
      check(fs::is_empty(directory),"Temporary files must be unlinked immediately");
      stream = sorter.finish();
      check(fd_count() <= before + 1,"Finish should retain only the final stream file");
      bool add_failed = false, finish_failed = false;
      try { sorter.add("key","[]"); } catch (const mvdb::Error& e) { add_failed = e.code == "STATE"; }
      try { sorter.finish(); } catch (const mvdb::Error& e) { finish_failed = e.code == "STATE"; }
      check(add_failed && finish_failed,"Completed sorter must reject reuse");
    }
    verify(*stream,expected,expected.size());
    stream.reset();
    check(fd_count() == before,"Stream destruction must close the final fd");
    for (auto budget : {size_t(256),size_t(4096),size_t(4*1024*1024)}) {
      mvdb::SpillSorter sorter(directory.string(),budget);
      for (const auto& r : records) sorter.add(r.key,r.row);
      auto limited = sorter.finish(17);
      verify(*limited,expected,17);
    }
    {
      mvdb::SpillSorter sorter(directory.string(),0);
      sorter.add("x","[1]");
      auto none = sorter.finish(0); verify(*none,{},0);
    }
    {
      mvdb::SpillSorter sorter(directory.string());
      auto empty = sorter.finish(); verify(*empty,{},100);
    }
    {
      mvdb::SpillSorter sorter(directory.string(),128);
      for (const auto& r : records) sorter.add(r.key,r.row);
      auto all = sorter.finish(UINT64_MAX); verify(*all,expected,expected.size());
    }
    {
      mvdb::SpillSorter sorter(directory.string(),1);
      sorter.add("not-finished","[1]");
    }
    check(fd_count() == before && fs::is_empty(directory),"Abandoned sorter must clean up files and descriptors");

    // A low descriptor limit exercises three-pass merging without one fd/run.
    pid_t child = ::fork();
    check(child >= 0,"fork failed");
    if (child == 0) {
      try {
        rlimit lim{}; if (::getrlimit(RLIMIT_NOFILE,&lim) != 0) _exit(10);
        lim.rlim_cur = std::min<rlim_t>(lim.rlim_max,16);
        if (::setrlimit(RLIMIT_NOFILE,&lim) != 0) _exit(11);
        mvdb::SpillSorter sorter(directory.string(),1);
        for (const auto& r : records) sorter.add(r.key,r.row);
        auto rows = sorter.finish(); verify(*rows,expected,expected.size());
        _exit(0);
      } catch (...) { _exit(12); }
    }
    int status = 0; check(::waitpid(child,&status,0) == child,"waitpid failed");
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0,"Merge must succeed with 16 allowed fds");

    // Force a real short write followed by EFBIG, rather than mocking I/O.
    child = ::fork(); check(child >= 0,"fork failed");
    if (child == 0) {
      ::signal(SIGXFSZ,SIG_IGN);
      rlimit lim{};
      if (::getrlimit(RLIMIT_FSIZE,&lim) != 0) _exit(30);
      lim.rlim_cur = std::min<rlim_t>(lim.rlim_max,1024);
      if (::setrlimit(RLIMIT_FSIZE,&lim) != 0) _exit(31);
      try {
        mvdb::SpillSorter sorter(directory.string(),1);
        sorter.add("key",std::string(8192,'x'));
        _exit(32);
      } catch (const mvdb::Error& e) { _exit(e.code == "IO" ? 0 : 33); }
      catch (...) { _exit(34); }
    }
    check(::waitpid(child,&status,0) == child,"waitpid failed");
    check(WIFEXITED(status) && WEXITSTATUS(status) == 0,"Short write/file-size failure must become Error IO");
    check(fs::is_empty(directory),"Failed writes must not leave named files");

    int pipefd[2]; check(::pipe(pipefd) == 0,"pipe failed");
    child = ::fork(); check(child >= 0,"fork failed");
    if (child == 0) {
      ::close(pipefd[0]);
      try {
        mvdb::SpillSorter sorter(directory.string(),1);
        for (const auto& r : records) sorter.add(r.key,r.row);
        const char ready = 'R'; if (::write(pipefd[1],&ready,1) != 1) _exit(20);
        for (;;) ::pause();
      } catch (...) { _exit(21); }
    }
    ::close(pipefd[1]); char ready = 0;
    const auto received = ::read(pipefd[0],&ready,1); ::close(pipefd[0]);
    check(received == 1 && ready == 'R',"Child did not prepare sort runs");
    check(::kill(child,SIGKILL) == 0,"kill failed");
    check(::waitpid(child,&status,0) == child && WIFSIGNALED(status),"Killed child must be reaped");
    check(fs::is_empty(directory),"SIGKILL must not leave sort artifacts");
    check(fd_count() == before,"Test must not leak parent descriptors");

    fs::remove_all(directory);
    std::cout << "spill checks passed: " << checks << '\n';
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << " (test directory " << directory << ")\n";
    return 1;
  }
}
