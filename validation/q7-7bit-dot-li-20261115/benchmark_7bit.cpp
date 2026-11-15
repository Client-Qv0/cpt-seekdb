#include "exact_cache.hpp"
#include "seven_bit.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr size_t rows = 8192;
constexpr size_t dim = 128;
constexpr size_t batch_rows = 32;
constexpr size_t distance_lanes = 4;
volatile uint64_t blackhole = 0;

uint64_t run_current(const std::vector<int8_t> &row_codes,
                     const std::vector<int16_t> &query, size_t batches) {
  uint64_t checksum = 0;
  const size_t mask = rows - 1;
  for (size_t batch = 0; batch < batches; ++batch) {
    const size_t begin = (batch * batch_rows) & mask;
    uint32_t output[batch_rows];
    for (size_t offset = 0; offset < batch_rows; offset += distance_lanes) {
      const int8_t *base = row_codes.data() + (begin + offset) * dim;
      mvdb::exact::quantized_squared_distance4_avx2(
          base, base + dim, base + 2 * dim, base + 3 * dim,
          query.data(), dim, output + offset);
    }
    for (uint32_t value : output) checksum += value;
  }
  blackhole ^= checksum;
  return checksum;
}

uint64_t run_seven_bit(const seven_bit::Rows &prepared,
                       const seven_bit::Query &query, size_t batches) {
  uint64_t checksum = 0;
  const size_t mask = rows - 1;
  for (size_t batch = 0; batch < batches; ++batch) {
    const size_t begin = (batch * batch_rows) & mask;
    uint32_t output[batch_rows];
    for (size_t offset = 0; offset < batch_rows; offset += 8) {
      seven_bit::squared_distances8(
          prepared.biased_codes.data() + (begin + offset) * dim,
          prepared.squared_norms.data() + begin + offset,
          query, dim, output + offset);
    }
    for (uint32_t value : output) checksum += value;
  }
  blackhole ^= checksum;
  return checksum;
}

template <class Function>
double measure(Function function, size_t batches) {
  const auto start = std::chrono::steady_clock::now();
  const uint64_t result = function(batches);
  const auto end = std::chrono::steady_clock::now();
  blackhole ^= result;
  return std::chrono::duration<double>(end - start).count();
}

double median(std::vector<double> values) {
  std::sort(values.begin(), values.end());
  return values[values.size() / 2];
}
}  // namespace

int main(int argc, char **argv) {
  size_t rounds = 7;
  size_t batches = 100000;
  if (argc == 3) {
    rounds = std::stoul(argv[1]);
    batches = std::stoul(argv[2]);
  } else if (argc != 1) {
    std::cerr << "usage: benchmark_7bit [rounds batches]\n";
    return 2;
  }
  if (!rounds || !batches) {
    std::cerr << "rounds and batches must be positive\n";
    return 2;
  }

  std::mt19937 rng(20261115);
  std::uniform_int_distribution<int> code(-64, 64);
  std::vector<int8_t> codes(rows * dim);
  std::vector<int16_t> current_query(dim);
  std::vector<int8_t> candidate_query(dim);
  for (auto &value : codes) value = static_cast<int8_t>(code(rng));
  for (size_t d = 0; d < dim; ++d) {
    const int8_t value = static_cast<int8_t>(code(rng));
    candidate_query[d] = value;
    current_query[d] = value;
  }
  seven_bit::Rows prepared = seven_bit::prepare_rows(codes, dim);
  seven_bit::Query query = seven_bit::prepare_query(candidate_query);

  for (size_t batch = 0; batch < 256; ++batch) {
    const size_t begin = (batch * batch_rows) & (rows - 1);
    uint32_t current[batch_rows], candidate[batch_rows];
    for (size_t offset = 0; offset < batch_rows; offset += distance_lanes) {
      const int8_t *base = codes.data() + (begin + offset) * dim;
      mvdb::exact::quantized_squared_distance4_avx2(
          base, base + dim, base + 2 * dim, base + 3 * dim,
          current_query.data(), dim, current + offset);
    }
    for (size_t offset = 0; offset < batch_rows; offset += 8) {
      seven_bit::squared_distances8(
          prepared.biased_codes.data() + (begin + offset) * dim,
          prepared.squared_norms.data() + begin + offset,
          query, dim, candidate + offset);
    }
    for (size_t lane = 0; lane < batch_rows; ++lane)
      if (current[lane] != candidate[lane])
        throw std::runtime_error("candidate and current kernels disagree");
  }

  run_current(codes, current_query, 100);
  run_seven_bit(prepared, query, 100);
  std::vector<double> current_times, control_times, candidate_times;
  std::vector<double> aa_ratios, ab_ratios;
  for (size_t round = 0; round < rounds; ++round) {
    // Palindrome A-A'-B-A'-A controls slow monotonic drift in the shared host.
    const double current_first =
        measure([&](size_t n) { return run_current(codes, current_query, n); },
                batches);
    const double control_first =
        measure([&](size_t n) { return run_current(codes, current_query, n); },
                batches);
    const double candidate =
        measure([&](size_t n) { return run_seven_bit(prepared, query, n); },
                batches);
    const double control_second =
        measure([&](size_t n) { return run_current(codes, current_query, n); },
                batches);
    const double current_second =
        measure([&](size_t n) { return run_current(codes, current_query, n); },
                batches);
    const double current = (current_first + current_second) / 2;
    const double control = (control_first + control_second) / 2;
    current_times.push_back(current);
    control_times.push_back(control);
    candidate_times.push_back(candidate);
    aa_ratios.push_back(current / control);
    ab_ratios.push_back(current / candidate);
    std::cout << "round=" << round + 1
              << " current=" << current
              << " control=" << control
              << " candidate=" << candidate
              << " current/candidate=" << current / candidate << '\n';
  }
  const double current_median = median(current_times);
  const double candidate_median = median(candidate_times);
  const double aa_median = median(aa_ratios);
  const double speedup = current_median / candidate_median;
  const size_t wins = std::count_if(
      ab_ratios.begin(), ab_ratios.end(), [](double value) { return value >= 1.25; });
  std::cout << "SUMMARY"
            << " rows=" << rows
            << " dim=" << dim
            << " batch_rows=" << batch_rows
            << " rounds=" << rounds
            << " timed_batches_per_call=" << batches
            << " aa_median_ratio=" << aa_median
            << " current_median_seconds=" << current_median
            << " candidate_median_seconds=" << candidate_median
            << " speedup=" << speedup
            << " rounds_at_or_above_1_25=" << wins
            << " rounds_total=" << rounds
            << " exact_batches_checked=256\n";
  return speedup >= 1.25 ? 0 : 1;
}
