#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>
#if defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))
#include <immintrin.h>
#endif

namespace seven_bit {

// The production int8 screen supports [-127, 127]. This candidate is enabled
// only when every stored and query code fits [-64, 64], allowing an exact
// unsigned-by-signed AVX2 product without saturation.
constexpr int bias = 64;

struct Query {
  std::vector<int8_t> codes;
  int32_t sum_codes = 0;
  int32_t squared_norm = 0;
};

struct Rows {
  size_t dim = 0;
  std::vector<uint8_t> biased_codes;
  std::vector<uint32_t> squared_norms;
};

inline Query prepare_query(const std::vector<int8_t> &codes) {
  Query query;
  query.codes = codes;
  for (int8_t code : codes) {
    if (code < -bias || code > bias)
      throw std::invalid_argument("query code outside [-64,64]");
    query.sum_codes += int32_t(code);
    query.squared_norm += int32_t(code) * int32_t(code);
  }
  return query;
}

inline Rows prepare_rows(const std::vector<int8_t> &codes, size_t dim) {
  if (!dim || codes.size() % dim)
    throw std::invalid_argument("row code array is not dimension aligned");
  Rows rows;
  rows.dim = dim;
  rows.biased_codes.resize(codes.size());
  rows.squared_norms.resize(codes.size() / dim);
  for (size_t row = 0; row < rows.squared_norms.size(); ++row) {
    uint32_t norm = 0;
    for (size_t d = 0; d < dim; ++d) {
      const int8_t code = codes[row * dim + d];
      if (code < -bias || code > bias)
        throw std::invalid_argument("row code outside [-64,64]");
      rows.biased_codes[row * dim + d] =
          static_cast<uint8_t>(int(code) + bias);
      norm += uint32_t(int(code) * int(code));
    }
    rows.squared_norms[row] = norm;
  }
  return rows;
}

inline uint32_t squared_distance_from_dot(int32_t dot_biased,
                                          uint32_t row_norm,
                                          const Query &query) {
  const int32_t base_dot = dot_biased - bias * query.sum_codes;
  const int64_t squared = int64_t(row_norm) + query.squared_norm -
                          2 * int64_t(base_dot);
  if (squared < 0 || squared > std::numeric_limits<uint32_t>::max())
    throw std::overflow_error("biased-dot squared distance out of range");
  return static_cast<uint32_t>(squared);
}

inline void squared_distances8(const uint8_t *biased_rows,
                               const uint32_t *row_norms,
                               const Query &query, size_t dim,
                               uint32_t *out) {
#if defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))
  __m256i sums[8] = {
      _mm256_setzero_si256(), _mm256_setzero_si256(),
      _mm256_setzero_si256(), _mm256_setzero_si256(),
      _mm256_setzero_si256(), _mm256_setzero_si256(),
      _mm256_setzero_si256(), _mm256_setzero_si256()};
  const __m256i ones = _mm256_set1_epi16(1);
  size_t d = 0;
  for (; d + 32 <= dim; d += 32) {
    const __m256i query_bytes = _mm256_loadu_si256(
        reinterpret_cast<const __m256i *>(query.codes.data() + d));
    for (size_t lane = 0; lane < 8; ++lane) {
      const uint8_t *row = biased_rows + lane * dim;
      const __m256i row_bytes = _mm256_loadu_si256(
          reinterpret_cast<const __m256i *>(row + d));
      const __m256i pairs = _mm256_maddubs_epi16(row_bytes, query_bytes);
      sums[lane] =
          _mm256_add_epi32(sums[lane], _mm256_madd_epi16(pairs, ones));
    }
  }
  for (size_t lane = 0; lane < 8; ++lane) {
    const __m128i halves = _mm_add_epi32(
        _mm256_castsi256_si128(sums[lane]),
        _mm256_extracti128_si256(sums[lane], 1));
    const __m128i combined = _mm_hadd_epi32(halves, halves);
    const __m128i total = _mm_hadd_epi32(combined, combined);
    int32_t dot = _mm_cvtsi128_si32(total);
    const uint8_t *row = biased_rows + lane * dim;
    for (size_t tail = d; tail < dim; ++tail)
      dot += int32_t(row[tail]) * int32_t(query.codes[tail]);
    out[lane] = squared_distance_from_dot(dot, row_norms[lane], query);
  }
#else
  for (size_t lane = 0; lane < 8; ++lane) {
    const uint8_t *row = biased_rows + lane * dim;
    int32_t dot = 0;
    for (size_t d = 0; d < dim; ++d)
      dot += int32_t(row[d]) * int32_t(query.codes[d]);
    out[lane] = squared_distance_from_dot(dot, row_norms[lane], query);
  }
#endif
}

inline void squared_distances8(const Rows &rows, const Query &query,
                               size_t dim, uint32_t *out) {
  if (rows.dim != dim || query.codes.size() != dim ||
      rows.squared_norms.size() < 8)
    throw std::invalid_argument("7-bit batch shape mismatch");
  squared_distances8(rows.biased_codes.data(), rows.squared_norms.data(),
                     query, dim, out);
}

}  // namespace seven_bit
