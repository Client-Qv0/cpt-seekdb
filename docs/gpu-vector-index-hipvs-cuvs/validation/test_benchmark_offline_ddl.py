"""CPU-only checks for benchmark truth and cached-input integrity."""
import tempfile
from pathlib import Path
import unittest

import numpy as np

from benchmark_offline_ddl import prepare


class DatasetTest(unittest.TestCase):
    def test_partial_chunk_truth_and_sql_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Leaves only 16 rows in the final exact-search chunk.
            prepare(root, 16400, 4, 3, 17)
            base = np.load(root / "base.npy")
            queries = np.load(root / "queries.npy")
            truth = np.load(root / "truth.npy")
            for i, query in enumerate(queries):
                distances = ((base.astype(np.float64) - query.astype(np.float64)) ** 2).sum(axis=1)
                expected = np.argsort(distances, kind="stable")[:100]
                np.testing.assert_array_equal(truth[i], expected)
            # Values sent through LOAD DATA must preserve the float32 inputs.
            for line, row in zip((root / "base.tsv").read_text().splitlines(), base):
                _, text = line.split("\t")
                restored = np.fromstring(text[1:-1], sep=",", dtype=np.float32)
                np.testing.assert_array_equal(restored, row)

    def test_cache_rejects_modified_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepare(root, 100, 4, 2, 17)
            with (root / "base.tsv").open("a") as out:
                out.write("corruption\n")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                prepare(root, 100, 4, 2, 17)


if __name__ == "__main__":
    unittest.main()
