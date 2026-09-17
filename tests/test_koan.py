from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt8_koan as koan


class KoanRegressionTests(unittest.TestCase):
    def test_source_reference_length(self):
        _, _, cipher, expected = koan.load_reference()
        self.assertEqual(len(cipher), 209)
        self.assertEqual(len(expected), 209)

    def test_registered_reverse_plus_three_is_exact(self):
        _, _, cipher, expected = koan.load_reference()
        self.assertEqual(koan.affine(cipher, 28, 2), expected)
        self.assertEqual(koan.affine(expected, 28, 2), cipher)

    def test_random_affine_controls_do_not_collide(self):
        _, _, cipher, expected = koan.load_reference()
        pairs = koan.control_pairs()
        self.assertEqual(len(pairs), 32)
        self.assertNotIn((28, 2), pairs)
        self.assertTrue(all(koan.affine(cipher, a, b) != expected for a, b in pairs))


if __name__ == "__main__":
    unittest.main()
