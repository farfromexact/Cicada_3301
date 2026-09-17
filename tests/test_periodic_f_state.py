from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.periodic_f_state import DEFAULT_KEY, scan_page
import attempt12_periodic_f_state as runner


class PeriodicFStateTests(unittest.TestCase):
    def test_ciphertext_f_keeps_exception_and_ordinary_paths(self):
        result = scan_page([1, 0])
        self.assertEqual(result["final_phases"], [1, 2])
        self.assertEqual(result["terminal_path_count_capped"], 2)
        self.assertEqual(result["exception_edges"], 1)
        self.assertEqual(result["ordinary_edges"], 2)

    def test_nonzero_cipher_that_decodes_to_f_is_dead(self):
        result = scan_page([1, DEFAULT_KEY[1]])
        self.assertEqual(result["final_state_count"], 0)
        self.assertEqual(result["first_dead_position"], 1)
        self.assertEqual(result["legal_prefix_length"], 1)

    def test_independent_recurrence_matches_pure_module(self):
        cipher = [0, 1, 0, 18, 4, 0, 7]
        expected = scan_page(cipher, start_phases=(0,))
        actual = runner.independent_scan(cipher, (0,), DEFAULT_KEY)
        self.assertEqual(actual, expected)

    def test_positive_generator_has_both_ciphertext_f_origins(self):
        plain = [0, 1, (-DEFAULT_KEY[1]) % 29, 0, 4]
        cipher, terminal, trace = runner.encrypt_plain(plain)
        self.assertEqual(cipher[:3], [0, 1, 0])
        self.assertEqual(trace[0]["kind"], "plaintext_f_exception")
        self.assertEqual(trace[2]["kind"], "ordinary_ciphertext_f")
        self.assertIn(terminal, scan_page(cipher)["final_phases"])

    def test_zero_preserving_shuffle_keeps_multiset_and_positions(self):
        values = [0, 1, 2, 0, 3, 4]
        shuffled = runner.randomize_preserving_zero_positions(values, random.Random(7))
        self.assertEqual([i for i, value in enumerate(values) if value == 0],
                         [i for i, value in enumerate(shuffled) if value == 0])
        self.assertEqual(sorted(value for value in values if value != 0),
                         sorted(value for value in shuffled if value != 0))


if __name__ == "__main__":
    unittest.main()
