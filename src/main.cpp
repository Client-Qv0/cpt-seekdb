#include "engine.hpp"
#include <iostream>
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
        auto result = engine.execute(sql);
        emitting = true;
        mvdb::write_result_json(std::cout, result);
        std::cout << '\n' << std::flush;
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
