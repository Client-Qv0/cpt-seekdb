#include "seven_bit.hpp"
#include <cstdint>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
void require(bool ok) {
  if (!ok) throw std::runtime_error("7-bit kernel check failed");
}
}

int main() {
  std::mt19937 rng(20261115);
  std::uniform_int_distribution<int> code(-64, 64);
  for (size_t dim : {size_t(1), size_t(7), size_t(15), size_t(16),
                     size_t(17), size_t(31), size_t(32), size_t(33),
                     size_t(127), size_t(128), size_t(129), size_t(8192)}) {
    std::vector<int8_t> signed_rows(8 * dim);
    std::vector<int8_t> signed_query(dim);
    for (auto &value : signed_rows) value = static_cast<int8_t>(code(rng));
    for (auto &value : signed_query) value = static_cast<int8_t>(code(rng));

    seven_bit::Query query = seven_bit::prepare_query(signed_query);
    seven_bit::Rows rows = seven_bit::prepare_rows(signed_rows, dim);
    uint32_t actual[8];
    seven_bit::squared_distances8(rows, query, dim, actual);
    for (size_t lane = 0; lane < 8; ++lane) {
      uint32_t expected = 0;
      for (size_t d = 0; d < dim; ++d) {
        const int delta = int(signed_rows[lane * dim + d]) -
                          int(signed_query[d]);
        expected += static_cast<uint32_t>(delta * delta);
      }
      if (actual[lane] != expected) {
        std::cerr << "dim=" << dim << " lane=" << lane
                  << " actual=" << actual[lane]
                  << " expected=" << expected << '\n';
      }
      require(actual[lane] == expected);
    }
  }

  constexpr size_t dim = 8192;
  std::vector<int8_t> low_row(8 * dim, -64), high_row(8 * dim, 64);
  std::vector<int8_t> low_query(dim, -64), high_query(dim, 64);
  seven_bit::Rows extreme_low = seven_bit::prepare_rows(low_row, dim);
  seven_bit::Rows extreme_high = seven_bit::prepare_rows(high_row, dim);
  seven_bit::Query q_low = seven_bit::prepare_query(low_query);
  seven_bit::Query q_high = seven_bit::prepare_query(high_query);
  uint32_t distance = 0;
  seven_bit::squared_distances8(extreme_low, q_low, dim, &distance);
  require(distance == 0);
  seven_bit::squared_distances8(extreme_high, q_low, dim, &distance);
  require(distance == 128u * 128u * dim);
  seven_bit::squared_distances8(extreme_high, q_high, dim, &distance);
  require(distance == 0);

  std::vector<int8_t> too_wide(1, 65);
  bool rejected = false;
  try {
    (void)seven_bit::prepare_rows(too_wide, 1);
  } catch (const std::invalid_argument &) {
    rejected = true;
  }
  require(rejected);
  std::cout << "7-bit biased-dot exactness and boundaries passed\n";
}
