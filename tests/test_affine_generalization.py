from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt9_affine_generalization as affine_test


class AffineGeneralizationTests(unittest.TestCase):
    def test_registered_map_is_an_involution(self):
        values = list(range(29))
        self.assertEqual(affine_test.affine(affine_test.affine(values, 28, 2), 28, 2), values)

    def test_raw_transform_preserves_non_runes(self):
        raw = "ᚠ-ᚢ / literal\n"
        decoded = affine_test.transform_raw(raw, 28, 2)
        self.assertEqual(decoded[1:], "-ᚢ / literal\n")

    def test_controls_are_unique_and_exclude_registered_map(self):
        pairs = affine_test.control_pairs()
        self.assertEqual(len(pairs), affine_test.CONTROL_COUNT)
        self.assertEqual(len(set(pairs)), affine_test.CONTROL_COUNT)
        self.assertNotIn((28, 2), pairs)
        self.assertTrue(all(1 <= a < 29 and 0 <= b < 29 for a, b in pairs))

    def test_corpus_applicability_is_pinned(self):
        pages = affine_test.load_pages()
        self.assertEqual(len(pages), 56)
        self.assertEqual([p["page"] for p in pages if not p["indices"]], ["LP2/50"])
        self.assertEqual(sum(p["rune_count"] for p in pages), 12956)


if __name__ == "__main__":
    unittest.main()
