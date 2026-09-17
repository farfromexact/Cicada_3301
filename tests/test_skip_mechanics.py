"""Tiny hand-computed mechanics tests, without real source candidates."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.runes import RUNES
from lp_lab.skip_mechanics import transform


class SkipMechanicsTests(unittest.TestCase):
    def test_specified_skip_consumption_distinguishes_following_letters(self):
        page = [{"page": "toy", "raw": RUNES[0] + "-" + RUNES[1] + RUNES[2]}]
        options = dict(key=(1, 2), specified_skip=(0,))
        none = transform(page, policy="none", **options)
        free = transform(page, policy="specified_free", **options)
        consume = transform(page, policy="specified_consume", **options)
        self.assertEqual(none["pages"][0]["indices"], [28, 28, 1])
        self.assertEqual(free["pages"][0]["indices"], [0, 0, 0])
        self.assertEqual(consume["pages"][0]["indices"], [0, 28, 1])
        self.assertEqual([step["clock_index"] for step in free["steps"]], [0, 0, 1])
        self.assertEqual([step["consumed"] for step in consume["steps"]], [True, True, True])
        self.assertEqual([none["final_clock"], free["final_clock"], consume["final_clock"]], [3, 2, 3])
        self.assertEqual([step["source_offset"] for step in free["steps"]], [0, 2, 3])

    def test_page_reset_changes_only_clock_not_global_skip_coordinates(self):
        pages = [{"page": "a", "raw": RUNES[4]}, {"page": "b", "raw": RUNES[0] + RUNES[4]}]
        options = dict(key=(1, 2), policy="specified_free", specified_skip=(1,))
        continuous = transform(pages, **options)
        reset = transform(pages, continuity="page_reset", **options)
        self.assertEqual(continuous["pages"][1]["indices"], [0, 2])
        self.assertEqual(reset["pages"][1]["indices"], [0, 3])
        self.assertEqual(reset["selected_skips"], [1])
        self.assertEqual([s["local_rune_ordinal"] for s in reset["steps"]], [0, 0, 1])
        self.assertEqual([s["global_rune_ordinal"] for s in reset["steps"]], [0, 1, 2])

    def test_prime_sequence_direction_and_literals(self):
        pages = [{"page": "toy", "raw": "\n" + RUNES[5] + "363\n&" + RUNES[5] + RUNES[5] + "./"}]
        subtract = transform(pages, mode="prime")
        add = transform(pages, mode="prime", direction="add")
        self.assertEqual(subtract["pages"][0]["indices"], [4, 3, 1])
        self.assertEqual(add["pages"][0]["indices"], [6, 7, 9])
        self.assertEqual([s["delta"] for s in subtract["steps"]], [1, 2, 4])
        self.assertEqual("".join(c for c in subtract["pages"][0]["raw"] if c not in RUNES), "\n363\n&./")

    def test_all_cipher_f_is_selected_from_input_only(self):
        pages = [{"page": "toy", "raw": RUNES[0] + RUNES[1] + RUNES[0] + RUNES[2]}]
        result = transform(pages, key=(1, 2), policy="all_cipher_f_free")
        self.assertEqual(result["selected_skips"], [0, 2])
        self.assertEqual(result["pages"][0]["indices"], [0, 0, 0, 0])
        self.assertEqual(result["final_clock"], 2)

    def test_plaintext_zero_requires_frozen_mask_for_inverse(self):
        source = [{"page": "toy", "raw": RUNES[1]}]
        decoded = transform(source, key=(1,), policy="all_cipher_f_free")
        self.assertEqual(decoded["pages"][0]["indices"], [0])
        self.assertEqual(decoded["selected_skips"], [])
        # Reselecting plaintext F silently changes the rule and is not inverse.
        wrong = transform([{"page": "toy", "raw": decoded["pages"][0]["raw"]}],
                          key=(1,), policy="all_cipher_f_free", direction="add")
        self.assertNotEqual(wrong["pages"][0]["raw"], source[0]["raw"])
        restored = [(s["output_index"] + s["delta"]) % 29 for s in decoded["steps"]]
        self.assertEqual(restored, [1])

    def test_invalid_parameters_and_answer_fields_rejected(self):
        page = [{"page": "toy", "raw": RUNES[0]}]
        for invalid in ((0, 0), (-1,), (1,), (True,)):
            with self.assertRaises(ValueError):
                transform(page, specified_skip=invalid)
        with self.assertRaises(ValueError):
            transform([{"page": "toy", "raw": RUNES[0], "expected": [0]}])
        with self.assertRaises(ValueError):
            transform(page, key=(29,))

    def test_unregistered_runic_unicode_is_rejected_not_treated_as_literal(self):
        with self.assertRaisesRegex(ValueError, "Unregistered rune.*on toy at 2"):
            transform([{"page": "toy", "raw": RUNES[0] + "-" + "\u16a1"}])


if __name__ == "__main__":
    unittest.main()
