from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_h030_stopping_v1 import finite_field_rank, order_cap_oracle


class H030StoppingAuditTests(unittest.TestCase):
    def test_rank_is_over_f29(self):
        self.assertEqual(finite_field_rank([[1, 1], [1, 30]]), 1)
        self.assertEqual(finite_field_rank([[1, 1], [1, 0]]), 2)

    def test_cap_accepts_lower_order_and_rejects_broken_prefix(self):
        seq = [1, 1]
        for _ in range(126):
            seq.append((seq[-1] + seq[-2]) % 29)
        self.assertTrue(order_cap_oracle(seq, 16)["consistent"])
        seq[-1] = (seq[-1] + 1) % 29
        self.assertFalse(order_cap_oracle(seq, 16)["consistent"])
        self.assertTrue(order_cap_oracle([0] * 128, 16)["consistent"])


if __name__ == "__main__":
    unittest.main()
