from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt7_legendre as legendre


class LegendreTests(unittest.TestCase):
    def test_three_valued_character(self):
        self.assertEqual(legendre.chi(0), 0)
        self.assertEqual(legendre.chi(1), 1)
        self.assertEqual(legendre.chi(28), 1)
        self.assertEqual(legendre.chi(2), -1)
        self.assertEqual(legendre.chi(27), -1)

    def test_vectorized_matches_manual(self):
        pages = [dict(indices=[0, 1, 2, 4, 28, 0], groups=[0] * 6,
                      segments=[[0, 6]], hyphen_mask=[False] * 6,
                      boundary_eligible=[True] * 6)]
        vector = legendre.vector_statistics(pages)
        manual = legendre.manual_statistics(pages)
        self.assertEqual(vector, manual)

    def test_synthetic_sensitivity(self):
        result = legendre.synthetic_sensitivity()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["later_projection_equal"])
        self.assertTrue(result["first_position_zero_preserved"])

    def test_corpus_shape(self):
        pages = legendre.load_pages()
        applicable = [page for page in pages if page["indices"]]
        self.assertEqual(len(applicable), 55)
        self.assertEqual(sum(len(page["indices"]) for page in applicable), 12956)
        self.assertEqual(len(legendre.vector_statistics(applicable)), 55 * 28)


if __name__ == "__main__":
    unittest.main()
