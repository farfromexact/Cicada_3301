from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt11_mobius_inversion as mobius


class MobiusInversionTests(unittest.TestCase):
    def test_inversion_is_an_involution(self):
        values = list(range(29))
        self.assertEqual(mobius.invert_values(mobius.invert_values(values)), values)
        self.assertEqual(mobius.inversion(0), 0)
        self.assertEqual(mobius.inversion(1), 1)

    def test_raw_transform_preserves_non_runes(self):
        raw = "ᚠ-ᚢ / literal\n"
        decoded = mobius.transform_raw(raw)
        self.assertEqual(decoded[1:], "-ᚢ / literal\n")

    def test_controls_are_unique_and_zero_preserving(self):
        mappings = mobius.random_control_maps()
        self.assertEqual(len(mappings), mobius.CONTROL_COUNT)
        self.assertEqual(len(set(mappings)), mobius.CONTROL_COUNT)
        registered = tuple(mobius.inversion(value) for value in range(29))
        self.assertNotIn(registered, mappings)
        self.assertTrue(all(mapping[0] == 0 and sorted(mapping[1:]) == list(range(1, 29))
                            for mapping in mappings))

    def test_corpus_applicability_is_pinned(self):
        pages = mobius.load_pages()
        self.assertEqual(len(pages), 56)
        self.assertEqual([p["page"] for p in pages if not p["indices"]], ["LP2/50"])
        self.assertEqual(sum(p["rune_count"] for p in pages), 12956)


if __name__ == "__main__":
    unittest.main()
