from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.runes import RUNES
from lp_lab.r015_pgl import (INFINITY, PGL_ORDER, image, inverse_mapping,
                             mapping, matrices, model_from_training,
                             pair_counts, score_counts, segment_points)


class R015PglTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrices = matrices()

    def test_full_representative_count(self):
        self.assertEqual(len(self.matrices), PGL_ORDER)
        self.assertEqual(len(set(self.matrices)), PGL_ORDER)

    def test_every_map_is_a_30_point_bijection(self):
        for matrix in self.matrices[::137]:
            table = mapping(matrix)
            self.assertEqual(sorted(table), list(range(INFINITY + 1)))
            self.assertEqual(inverse_mapping(table)[table[3]], 3)

    def test_pole_and_infinity_rules(self):
        matrix = (2, 3, 1, 4)
        self.assertEqual(image(25, matrix), INFINITY)  # -4 mod29
        self.assertEqual(image(INFINITY, matrix), 2)
        affine = (7, 8, 0, 1)
        self.assertEqual(image(INFINITY, affine), INFINITY)

    def test_only_literal_hyphen_is_a_point(self):
        segments, counts = segment_points("ᚠ-ᚢ/ᚦ;123", RUNES)
        self.assertEqual(segments, [[0, INFINITY, 1], [2]])
        self.assertEqual(counts["literal_separator"], 1)
        self.assertEqual(counts["slash_boundaries"], 1)
        self.assertEqual(counts["other_hard_boundaries"], 4)

    def test_pair_score_is_finite(self):
        segments, _ = segment_points("ᚠ-ᚢ", RUNES)
        model = model_from_training([[0, INFINITY, 1]])
        self.assertTrue(score_counts(mapping((1, 0, 0, 1)), pair_counts(segments), model) < 0)


if __name__ == "__main__":
    unittest.main()
