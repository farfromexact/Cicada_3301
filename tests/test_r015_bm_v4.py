from itertools import product
from pathlib import Path
import random
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import attempt21_bm_v2 as reference
HAS_ACCELERATOR = all(importlib.util.find_spec(name) is not None for name in ("numpy", "numba"))
if HAS_ACCELERATOR:
    from lp_lab import r015_bm_v4 as fast


@unittest.skipUnless(HAS_ACCELERATOR, "optional archived BM acceleration requires numpy and numba")
class BmV4EquivalenceTests(unittest.TestCase):
    def test_exhaustive_short_field_sequences(self):
        for length in range(4):
            for values in product(range(29), repeat=length):
                seq = list(values)
                self.assertEqual(fast.bm(seq), reference.independent_bm(seq))

    def test_long_boundary_and_recurrence_metrics(self):
        rng = random.Random(33011904)
        cases = []
        for n in (0, 1, 2, 63, 64, 95, 96, 97, 128, 192, 224, 512):
            cases.extend(([0] * n, [28] * n, [rng.randrange(29) for _ in range(n)]))
        for order in (1, 2, 4, 8, 16, 17, 32):
            seq = reference.make_recurrence(256, order, rng)
            cases.extend((seq, seq[:-1] + [(seq[-1] + 1) % 29]))
        for sequence in cases:
            expected = reference.compact_metrics({"x": reference.independent_metrics(sequence)})["x"]
            self.assertEqual(fast.metrics(sequence), expected)

    def test_gaussian_oracle_minimal_order(self):
        rng = random.Random(33011905)
        for order in range(1, 9):
            seq = reference.make_recurrence(96, order, rng)
            fit = fast.bm(seq)
            self.assertTrue(fast.consistent_recurrence(seq, fit["order"]))
            for smaller in range(fit["order"]):
                self.assertFalse(fast.consistent_recurrence(seq, smaller))


if __name__ == "__main__":
    unittest.main()
