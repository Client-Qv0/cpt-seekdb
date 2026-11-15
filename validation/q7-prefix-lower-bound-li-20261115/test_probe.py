import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe import (  # noqa: E402
    build_quantizer,
    prefix_squared_lower_bound,
    safe_above,
    simulate_prefixes,
)


class PrefixLowerBoundTests(unittest.TestCase):
    def test_both_bounds_never_exceed_true_squared_distance(self):
        rng = np.random.default_rng(20261115)
        stored = rng.uniform(-1, 1, size=(29, 37)).astype(np.float32)
        queries = rng.uniform(-1, 1, size=(5, 37)).astype(np.float32)
        quantizer = build_quantizer(stored)
        row_codes = quantizer.codes(stored)
        query_codes = quantizer.codes(queries)

        exact = np.sum(
            (
                stored.astype(np.float64)[:, None, :]
                - queries.astype(np.float64)[None, :, :]
            )
            ** 2,
            axis=2,
            dtype=np.float64,
        )
        for prefix in (0, 1, 7, 16, 32, 37):
            coarse = prefix_squared_lower_bound(
                row_codes, query_codes, queries, quantizer.step, prefix, "coarse"
            )
            tight = prefix_squared_lower_bound(
                row_codes, query_codes, queries, quantizer.step, prefix, "tight"
            )
            self.assertTrue(np.all(coarse >= 0))
            self.assertTrue(np.all(tight >= coarse - 1e-30))
            self.assertTrue(np.all(coarse <= exact + 1e-15))
            self.assertTrue(np.all(tight <= exact + 1e-15))

    def test_sqrt_rejection_leaves_one_ulp_margin(self):
        worst = 1.0
        self.assertFalse(safe_above(worst, worst))
        self.assertFalse(safe_above(math.nextafter(worst, math.inf), worst))
        self.assertTrue(safe_above(math.nextafter(
            math.nextafter(worst, math.inf), math.inf
        ), worst))

    def test_quantizer_rejects_values_that_do_not_fit_int8(self):
        quantizer = build_quantizer(np.asarray([[1.0, -1.0]], dtype=np.float32))
        with self.assertRaises(ValueError):
            quantizer.codes(np.asarray(
                [[quantizer.step * 128, quantizer.step * -128]],
                dtype=np.float64,
            ))

    def test_zero_rejection_simulation_returns_exact_topk(self):
        rng = np.random.default_rng(17)
        count = 2000
        distances = rng.random(count)
        keys = np.arange(count)
        lowered = {
            method: {prefix: np.zeros(count) for prefix in (16, 32, 64, 96)}
            for method in ("coarse", "tight")
        }
        expected = [
            (int(key), float(distance))
            for distance, key in sorted(zip(distances, keys))[:10]
        ]
        simulated = simulate_prefixes(distances, keys, lowered)
        for result in simulated.values():
            self.assertEqual(result["returned"], expected)


if __name__ == "__main__":
    unittest.main()
