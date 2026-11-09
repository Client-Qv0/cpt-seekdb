#!/usr/bin/env python3
"""Check that the post-restart audit rejects bad or missing persisted data."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import benchmark_public_validation as benchmark


class FakeDatabase:
    response = None

    def __init__(self, *args, **kwargs):
        self.record = {}

    def query(self, sql, timeout):
        return self.response

    def close(self, **kwargs):
        pass


class ReadbackTest(unittest.TestCase):
    def audit(self, rows):
        FakeDatabase.response = {'ok': True, 'columns': ['id', 'grp', 'v'], 'rows': rows}
        expected = (np.array([0, 1]), np.array([0, 1]), np.array([[1, 2], [3, 4]], dtype=np.float32))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(benchmark.oracle, 'DIMENSION', 2), \
                mock.patch.object(benchmark.paired, 'resources', return_value={'healthy': True}):
            return benchmark.readback(FakeDatabase, Path('binary'), Path('data'), 'image', 'socket',
                                      '0,1', expected, Path(directory) / 'readback.json.gz')

    def test_exact_records_pass(self):
        result = self.audit([[0, 'g0', [1, 2]], [1, 'g1', [3, 4]]])
        self.assertTrue(result['passed'])
        self.assertEqual(result['checked_rows'], 2)

    def test_missing_duplicate_and_corrupt_records_fail(self):
        for rows in ([[0, 'g0', [1, 2]]],
                     [[0, 'g0', [1, 2]], [0, 'g0', [1, 2]]],
                     [[0, 'g0', [1, 2]], [1, 'g1', [3, 5]]],
                     [[0, 'g0', [1, 2]], [1, 'g1', [3, '4']]]):
            with self.subTest(rows=rows):
                self.assertFalse(self.audit(rows)['passed'])


if __name__ == '__main__':
    unittest.main()
