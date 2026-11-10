#include "engine.hpp"
#include "protocol.hpp"
#include <iostream>
#include <memory>
#include <string>

int main(int argc, char **argv) {
  // Protocol I/O uses C++ streams exclusively and flushes every response.
  std::ios::sync_with_stdio(false);
  std::cin.tie(nullptr);
  std::string directory = "/data";
  bool development = false;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--data-dir" && i + 1 < argc)
      directory = argv[++i];
    else if (arg == "--dev-protocol")
      development = true;
    else {
      std::cerr << "Usage: minivectordb [--data-dir PATH] [--dev-protocol]\n";
      return 2;
    }
  }
  try {
    std::cout.exceptions(std::ios::badbit | std::ios::failbit);
    auto engine = std::make_unique<mvdb::Engine>(directory);
    // Engine construction opens the data directory and completes recovery.
    if (!development)
      std::cout << "{\"type\":\"ready\"}\n" << std::flush;
    std::string line;
    while (std::getline(std::cin, line)) {
      mvdb::Request request;
      bool emitting = false, closing = false;
      try {
        if (!development) {
          mvdb::parse_request(line, request);
          if (request.op == mvdb::Request::Op::Shutdown) {
            closing = true;
            engine->prepare_shutdown();
            engine.reset();
            emitting = true;
            std::cout << "{\"id\":" << request.id_json << ",\"ok\":true}\n"
                      << std::flush;
            return 0;
          }
        }
        auto result = development ? engine->execute(line)
                                  : engine->execute(request.sql, request.search_mode);
        emitting = true;
        if (development)
          mvdb::write_result_json(std::cout, result);
        else
          mvdb::write_protocol_result_json(std::cout, result, request.id_json);
        std::cout << '\n' << std::flush;
      } catch (const mvdb::Error &e) {
        if (emitting) {
          // Streaming may fail after part of a JSON response has been written.
          // Never append a second error response to that partial message.
          std::cerr << "Result stream failed: " << e.what() << '\n';
          return 1;
        }
        if (development)
          std::cout << mvdb::error_json(e.code, e.what()) << '\n' << std::flush;
        else
          std::cout << mvdb::protocol_error_json(request.id_json, e.code, e.what())
                    << '\n' << std::flush;
        if (closing)
          return 1;
      } catch (const std::exception &e) {
        std::cerr << "Fatal execution error: " << e.what() << '\n';
        return 1;
      }
    }
    if (!std::cin.eof()) {
      std::cerr << "Failed to read protocol input\n";
      return 1;
    }
    engine->prepare_shutdown();
    engine.reset();
  } catch (const std::exception &e) {
    std::cerr << "Database startup or I/O failure: " << e.what() << '\n';
    return 1;
  }
  return 0;
}

