#include "storage.hpp"
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <string>
#include <sys/resource.h>

static int64_t micros(const timeval &v) {
  return int64_t(v.tv_sec) * 1000000 + v.tv_usec;
}

int main(int argc, char **argv) {
  std::string directory = "/data";
  for (int i = 1; i < argc; ++i)
    if (std::string(argv[i]) == "--data-dir" && i + 1 < argc)
      directory = argv[++i];
  try {
    rusage before{}, after{};
    if (getrusage(RUSAGE_SELF, &before)) return 3;
    const auto begin = std::chrono::steady_clock::now();
    auto store = std::make_unique<mvdb::Store>(directory);
    const auto end = std::chrono::steady_clock::now();
    if (getrusage(RUSAGE_SELF, &after)) return 3;
    const auto nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count();
    std::string command;
    while (std::getline(std::cin, command)) {
      std::istringstream input(command);
      std::string operation, table;
      input >> operation;
      if (operation == "READY") {
        std::cout << "{\"ok\":true,\"restore_nanoseconds\":" << nanos
                  << ",\"restore_user_microseconds\":" << micros(after.ru_utime) - micros(before.ru_utime)
                  << ",\"restore_system_microseconds\":" << micros(after.ru_stime) - micros(before.ru_stime)
                  << ",\"restore_minor_faults\":" << after.ru_minflt - before.ru_minflt
                  << ",\"restore_major_faults\":" << after.ru_majflt - before.ru_majflt
                  << "}\n" << std::flush;
      } else if (operation == "GET") {
        int64_t key;
        if (!(input >> table >> key)) return 2;
        const auto value = store->get(table, key);
        std::cout << "{\"ok\":true,\"key\":" << key << ",\"found\":" << (value ? "true" : "false");
        if (value) {
          std::cout << ",\"bytes\":" << value->size() << ",\"hex\":\"";
          constexpr char digits[] = "0123456789abcdef";
          for (unsigned char c : *value) std::cout << digits[c >> 4] << digits[c & 15];
          std::cout << '"';
        }
        std::cout << "}\n" << std::flush;
      } else if (operation == "SCAN") {
        if (!(input >> table)) return 2;
        uint64_t count = 0, bytes = 0, digest = 14695981039346656037ULL;
        int64_t minimum = std::numeric_limits<int64_t>::max();
        int64_t maximum = std::numeric_limits<int64_t>::min();
        store->scan(table, [&](int64_t key, const std::string &value) {
          ++count;
          bytes += value.size();
          minimum = std::min(minimum, key);
          maximum = std::max(maximum, key);
          uint64_t bits = static_cast<uint64_t>(key);
          for (unsigned i = 0; i < 8; ++i) { digest ^= (bits >> (i * 8)) & 255; digest *= 1099511628211ULL; }
          for (unsigned char c : value) { digest ^= c; digest *= 1099511628211ULL; }
        });
        std::cout << "{\"ok\":true,\"count\":" << count << ",\"payload_bytes\":" << bytes
                  << ",\"min_key\":" << minimum << ",\"max_key\":" << maximum
                  << ",\"fnv1a64_noncryptographic\":" << digest << "}\n" << std::flush;
      } else return 2;
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
