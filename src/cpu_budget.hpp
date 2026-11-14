#pragma once
// Process CPU budget: the smaller of the CPUs this process may run on and the
// CPU-time quota of its cgroup. Docker's --cpus creates a quota without a
// cpuset, so the affinity mask alone overstates how much CPU time is granted.
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>
#if defined(__linux__)
#include <sched.h>
#endif

namespace mvdb::cpu {
// CPUs this process may run on right now.
inline size_t affinity_cpus() {
#if defined(__linux__)
  cpu_set_t set;
  CPU_ZERO(&set);
  if (sched_getaffinity(0, sizeof(set), &set) == 0) {
    const int count = CPU_COUNT(&set);
    if (count > 0) return static_cast<size_t>(count);
  }
#endif
  const size_t count = std::thread::hardware_concurrency();
  return count ? count : 1;
}
// cgroup v2 cpu.max: "<quota> <period>", quota "max" means unlimited.
inline double parse_cpu_max(const std::string &text) {
  size_t pos = 0;
  while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\t')) ++pos;
  const size_t begin = pos;
  while (pos < text.size() && text[pos] != ' ' && text[pos] != '\t' &&
         text[pos] != '\n')
    ++pos;
  const std::string quota = text.substr(begin, pos - begin);
  if (quota.empty() || quota == "max") return 0;
  const long long q = std::strtoll(quota.c_str(), nullptr, 10);
  if (q <= 0) return 0;
  long long period = 100000;
  while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\t')) ++pos;
  if (pos < text.size()) {
    const long long p = std::strtoll(text.c_str() + pos, nullptr, 10);
    if (p > 0) period = p;
  }
  return static_cast<double>(q) / static_cast<double>(period);
}
// cgroup v1 quota/period in microseconds; a non-positive quota means unlimited.
inline double parse_v1_quota(long long quota, long long period) {
  if (quota <= 0) return 0;
  if (period <= 0) period = 100000;
  return static_cast<double>(quota) / static_cast<double>(period);
}
inline std::string read_small_file(const char *path) {
  std::ifstream in(path);
  if (!in) return {};
  std::string text;
  std::getline(in, text);
  return text;
}
// Fractional CPU quota of this process's cgroup; 0 when unlimited or unknown.
// Walks from the mount root down to the cgroup in /proc/self/cgroup because a
// limit may sit on any ancestor: Docker puts it on the container root, systemd
// scopes put it one level below system.slice.
inline double cgroup_quota_cpus() {
#if defined(__linux__)
  const std::string self = read_small_file("/proc/self/cgroup");
  std::string relative;
  const size_t marker = self.find("0::");
  if (marker != std::string::npos) {
    relative = self.substr(marker + 3);
    while (!relative.empty() && (relative.back() == '\n' || relative.back() == ' '))
      relative.pop_back();
  }
  std::string base = "/sys/fs/cgroup";
  double quota = 0;
  for (;;) {
    if (const std::string text = read_small_file((base + "/cpu.max").c_str());
        !text.empty()) {
      const double value = parse_cpu_max(text);
      if (value > 0 && (quota == 0 || value < quota)) quota = value;
    }
    if (relative.empty() || relative == "/") break;
    if (relative.front() == '/') relative.erase(0, 1);
    const size_t slash = relative.find('/');
    base += "/" + relative.substr(0, slash);
    relative = slash == std::string::npos ? "" : relative.substr(slash);
  }
  if (quota > 0) return quota;
  // cgroup v1 keeps the cpu controller in its own mounted hierarchy.
  const long long v1_quota =
      std::strtoll(read_small_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").c_str(),
                   nullptr, 10);
  const long long v1_period =
      std::strtoll(read_small_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us").c_str(),
                   nullptr, 10);
  return parse_v1_quota(v1_quota, v1_period);
#else
  return 0;
#endif
}
// Width used for a scan. A quota below one CPU still yields one worker.
inline size_t effective_width(size_t affinity, double quota, size_t cap) {
  size_t width = affinity ? affinity : 1;
  if (quota > 0) {
    size_t granted = static_cast<size_t>(std::ceil(quota));
    if (granted < 1) granted = 1;
    if (granted < width) width = granted;
  }
  if (cap && width > cap) width = cap;
  return width ? width : 1;
}
// Cached once: the quota and affinity mask do not change during a run and the
// query path must not stat files per statement.
inline size_t budget_cpus() {
  static const size_t width = effective_width(affinity_cpus(), cgroup_quota_cpus(), 64);
  return width;
}
// Bytes this process may use, or 0 when no limit is known. cgroup v2 keeps the
// limit in memory.max with "max" meaning unlimited; v1 has its own hierarchy and
// a very large sentinel for unlimited. A limit may sit on any ancestor, so this
// walks the same path as the CPU quota.
inline size_t memory_limit_bytes() {
#if defined(__linux__)
  const std::string self = read_small_file("/proc/self/cgroup");
  std::string relative;
  const size_t marker = self.find("0::");
  if (marker != std::string::npos) {
    relative = self.substr(marker + 3);
    while (!relative.empty() && (relative.back() == '\n' || relative.back() == ' '))
      relative.pop_back();
  }
  auto parse = [](const std::string &text) -> size_t {
    if (text.empty() || text.rfind("max", 0) == 0) return 0;
    const long long value = std::strtoll(text.c_str(), nullptr, 10);
    // v1 reports a page-aligned "unlimited" value far above any real container.
    if (value <= 0 || value > (1LL << 46)) return 0;
    return static_cast<size_t>(value);
  };
  std::string base = "/sys/fs/cgroup";
  size_t limit = 0;
  for (;;) {
    const size_t value = parse(read_small_file((base + "/memory.max").c_str()));
    if (value && (limit == 0 || value < limit)) limit = value;
    if (relative.empty() || relative == "/") break;
    if (relative.front() == '/') relative.erase(0, 1);
    const size_t slash = relative.find('/');
    base += "/" + relative.substr(0, slash);
    relative = slash == std::string::npos ? "" : relative.substr(slash);
  }
  if (limit) return limit;
  return parse(read_small_file("/sys/fs/cgroup/memory/memory.limit_in_bytes"));
#else
  return 0;
#endif
}
} // namespace mvdb::cpu
