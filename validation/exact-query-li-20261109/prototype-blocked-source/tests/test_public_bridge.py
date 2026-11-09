import unittest
from public_samples import compare_rows
class Assertions(unittest.TestCase):
 def test_duplicates_preserved(self):
  self.assertFalse(compare_rows([[1],[1]],[[1],[2]],True))
 def test_unordered(self):
  self.assertTrue(compare_rows([[2],[1]],[[1],[2]],True))
 def test_bigint_exact(self):
  self.assertFalse(compare_rows([[9007199254740992]],[[9007199254740993]],False))
 def test_float_tolerance(self):
  self.assertTrue(compare_rows([[1.000001]],[[1.0]],False))
if __name__=='__main__':unittest.main()
