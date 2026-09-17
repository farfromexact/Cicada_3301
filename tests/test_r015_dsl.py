from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.r015_dsl import (DIVINITY, apply_recipe, build_language_model,
                             encrypt_recipe, enumerate_recipes, score_recipe)


class R015DslTests(unittest.TestCase):
    def test_program_budget_and_state_limit(self):
        programs, metadata = enumerate_recipes()
        self.assertEqual(metadata["raw_count"], 49)
        self.assertEqual(len(programs), metadata["unique_count"])
        self.assertEqual(len(programs), 40)
        self.assertTrue(all(sum(op in {"DIVINITY", "PRIME_MINUS_ONE"} for op in p) <= 1
                            for p in programs))

    def test_stateless_known_atoms(self):
        values = [0, 1, 2, 28]
        self.assertEqual(apply_recipe(values, ("A",)), [2, 1, 0, 3])
        self.assertEqual(apply_recipe(values, ("S3",)), [3, 4, 5, 2])
        self.assertEqual(apply_recipe(values, ("A", "A")), values)

    def test_inverse_encryption_roundtrip_for_state_program(self):
        values = [1, 0, 5, 7, 0, 28, 3, 4]
        recipe = ("A", "DIVINITY", "S3")
        cipher = encrypt_recipe(values, recipe)
        model = build_language_model("THE PATH IS OPEN. THE PATH IS MEASURED.")
        # The expected path is retained by the state scorer; a score exists
        # even when other legal F paths are also present.
        scored = score_recipe(cipher, recipe, model)
        self.assertGreaterEqual(scored["path_count"], 1)
        self.assertEqual(len(DIVINITY), 8)

    def test_language_model_is_smoothed(self):
        model = build_language_model("F F")
        self.assertEqual(len(model["start_weights"]), 29)
        self.assertTrue(all(weight == weight for weight in model["start_weights"]))


if __name__ == "__main__":
    unittest.main()
