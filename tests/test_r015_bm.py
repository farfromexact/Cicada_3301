from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.r015_bm import berlekamp_massey, metrics, predict_suffix, views


class R015BmTests(unittest.TestCase):
    def test_constant_and_zero_sequences(self):
        self.assertEqual(berlekamp_massey([0] * 12)["order"], 0)
        self.assertEqual(berlekamp_massey([3] * 12)["order"], 1)

    def test_known_recurrence_predicts_suffix(self):
        sequence = [1, 1]
        for _ in range(20):
            sequence.append((sequence[-1] + sequence[-2]) % 29)
        bm = berlekamp_massey(sequence[:12])
        self.assertLessEqual(bm["order"], 2)
        self.assertEqual(predict_suffix(sequence[:12], len(sequence) - 12, bm["connection"]), sequence[12:])

    def test_view_lengths_and_difference_boundary(self):
        result = views([1, 4, 9, 16])
        self.assertEqual(len(result["raw"]), 4)
        self.assertEqual(len(result["difference"]), 3)
        self.assertEqual(result["difference"], [3, 5, 7])
        self.assertEqual(len(result["gp_projection"]), 4)

    def test_short_status_is_explicit(self):
        self.assertEqual(metrics([1] * 20)["status"], "inconclusive_short")


if __name__ == "__main__":
    unittest.main()
