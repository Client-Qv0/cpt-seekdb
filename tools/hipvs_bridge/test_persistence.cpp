#include "seekdb_cuvs_bridge.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <set>
#include <vector>

int main(int argc, char **argv)
{
  if (argc != 3) return 2;
  const long count = 10000;
  const long dimension = 32;
  std::vector<float> vectors(count * dimension);
  for (long row = 0; row < count; ++row) {
    for (long column = 0; column < dimension; ++column) {
      vectors[row * dimension + column] = std::sin(float(row * 31 + column * 17));
    }
  }
  void *index = nullptr;
  if (std::strcmp(argv[1], "write") == 0) {
    index = seekdb_cuvs_build(vectors.data(), count, dimension);
    if (!index || seekdb_cuvs_serialize(index, argv[2]) != 0) return 3;
  } else {
    void *invalid = seekdb_cuvs_deserialize(argv[2], count - 1, dimension);
    if (invalid) { seekdb_cuvs_free(invalid); return 6; }
    invalid = seekdb_cuvs_deserialize(argv[2], count, dimension + 1);
    if (invalid) { seekdb_cuvs_free(invalid); return 7; }
    index = seekdb_cuvs_deserialize(argv[2], count, dimension);
    if (!index) return 4;
  }
  // Exercise both SQL-like single queries and batches before/after reload.
  // Top-200 requires itopk_size >= 800 and exposes the old implicit
  // SINGLE_CTA default's 512-candidate limit on the supported hipVS runtime.
  for (const long nq : {1L, 3L}) {
    std::vector<float> queries(nq * dimension);
    for (long q = 0; q < nq; ++q) {
      std::memcpy(queries.data() + q * dimension,
                  vectors.data() + q * (count / 3) * dimension,
                  dimension * sizeof(float));
    }
    for (const long topk : {10L, 200L}) {
      std::vector<unsigned int> ids(nq * topk);
      std::vector<float> distances(nq * topk);
      const int result = seekdb_cuvs_search(index, queries.data(), nq, topk,
                                           ids.data(), distances.data());
      if (result != 0) { seekdb_cuvs_free(index); return 5; }
      for (long q = 0; q < nq; ++q) {
        std::set<unsigned int> seen;
        for (long k = 0; k < topk; ++k) {
          const long pos = q * topk + k;
          if (ids[pos] >= count || !seen.insert(ids[pos]).second ||
              !std::isfinite(distances[pos]) || distances[pos] < -0.0001f) {
            seekdb_cuvs_free(index); return 8;
          }
        }
        if (ids[q * topk] != q * (count / 3) ||
            std::fabs(distances[q * topk]) > 0.0001f) {
          seekdb_cuvs_free(index); return 9;
        }
      }
      std::printf("%s: n=%ld nq=%ld topk=%ld unique_ids=1 exact_self=1\n",
                  argv[1], count, nq, topk);
    }
  }
  seekdb_cuvs_free(index);
  return 0;
}
