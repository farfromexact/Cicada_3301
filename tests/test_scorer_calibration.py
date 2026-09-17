import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt5_scorer_calibration as calibration


class ScorerCalibrationTests(unittest.TestCase):
    def test_independent_sieve_and_candidate_count(self):
        primes = calibration.independent_primes(300)
        self.assertEqual(len(primes), 300)
        self.assertEqual(primes[:5], [2, 3, 5, 7, 11])
        train = calibration.encode_text((ROOT / "data/synthetic/training.txt").read_text(encoding="utf8"))
        counts = [train.count(i) for i in range(29)]
        cipher, answer = calibration.generate(
            calibration.encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))[:256], 417)
        replay = calibration.expected_worker(cipher, counts)
        self.assertEqual(len(replay["rankings"]), 928)
        self.assertEqual(replay["selected"]["offset"], answer["key"]["offset"])
        self.assertEqual(replay["selected"]["shift"], answer["key"]["shift"])

    def test_plan_has_fixed_8_8_and_20_20_cases(self):
        held = calibration.encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))
        plans = calibration.make_plan(len(held))
        self.assertEqual(len(plans), 56)
        for phase, count in (("calibration", 16), ("evaluation", 40)):
            rows = [p for p in plans if p["phase"] == phase]
            self.assertEqual(len(rows), count)
            self.assertEqual(sum(p["kind"] == "positive" for p in rows), count // 2)
            self.assertEqual(sum(p["kind"] == "random_control" for p in rows), count // 2)

    def test_positive_private_roundtrip(self):
        held = calibration.encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))
        train = calibration.encode_text((ROOT / "data/synthetic/training.txt").read_text(encoding="utf8"))
        counts = [train.count(i) for i in range(29)]
        plan = next(p for p in calibration.make_plan(len(held)) if p["kind"] == "positive")
        cipher, private, public = calibration.generate_case(plan, held, counts)
        self.assertEqual(len(cipher), 256)
        key = private["key"]
        primes = calibration.independent_primes(256 + key["offset"])
        self.assertEqual([(p + primes[i + key["offset"]] - key["shift"]) % 29
                          for i, p in enumerate(private["plaintext"])], cipher)
        self.assertEqual(public["schema"], 1)


if __name__ == "__main__":
    unittest.main()
