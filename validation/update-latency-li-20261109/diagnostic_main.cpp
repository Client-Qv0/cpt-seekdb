#include "engine.hpp"
#include <iostream>
#include <chrono>
#include <string>

int main(int argc, char **argv) {
  std::string directory = "/data";
  bool development = false;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--data-dir" && i + 1 < argc)
      directory = argv[++i];
    else if (arg == "--dev-protocol")
      development = true;
    else {
      std::cerr << "Usage: minivectordb --data-dir PATH --dev-protocol\n";
      return 2;
    }
  }
  if (!development) {
    std::cerr << "Official protocol adapter pending published test driver. Use "
                 "--dev-protocol for local validation.\n";
    return 2;
  }
  try {
    std::cout.exceptions(std::ios::badbit | std::ios::failbit);
    mvdb::Engine engine(directory);
    std::string sql;
    while (std::getline(std::cin, sql)) {
      bool emitting = false;
      try {
        using Clock = std::chrono::steady_clock;
        const bool trace = sql == "UPDATE items SET x=999 WHERE id=0;" ||
                           sql == "SELECT x FROM items WHERE id=0;";
        const auto start = Clock::now();
        auto result = engine.execute(sql);
        const auto executed = Clock::now();
        emitting = true;
        mvdb::write_result_json(std::cout, result);
        const auto serialized = Clock::now();
        std::cout << '\n' << std::flush;
        const auto flushed = Clock::now();
        if (trace) {
          auto ns = [](auto a, auto b) {
            return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();
          };
          std::cerr << "DIAGNOSTIC {\"statement\":\""
                    << (sql[0] == 'U' ? "UPDATE" : "SELECT")
                    << "\",\"engine_ns\":" << ns(start, executed)
                    << ",\"serialize_ns\":" << ns(executed, serialized)
                    << ",\"flush_ns\":" << ns(serialized, flushed) << "}\n";
        }
      } catch (const mvdb::Error &e) {
        if (emitting) {
          // A failed stream cannot be replaced by a second JSON object after a
          // partial response. Close the process and let the caller detect EOF.
          std::cerr << "Result stream failed: " << e.what() << '\n';
          return 1;
        }
        std::cout << mvdb::error_json(e.code, e.what()) << '\n' << std::flush;
      } catch (const std::exception &e) {
        std::cerr << "Fatal execution error: " << e.what() << '\n';
        return 1;
      }
    }
  } catch (const std::exception &e) {
    std::cerr << "Database startup failure: " << e.what() << '\n';
    return 1;
  }
}
