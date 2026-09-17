from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.reachability import prime_deltas, scan_cipher


class ReachabilityTests(unittest.TestCase):
    def test_prime_deltas_use_prime_minus_one_mod29(self):
        self.assertEqual(prime_deltas(5), (1, 2, 4, 6, 10))

    def test_zero_cipher_has_copy_and_ordinary_transitions(self):
        # Plain [F, U] encrypts to [F, U+delta0] = [0, 2].  The first
        # ciphertext F may stay at t=0, while the later ordinary branch dies
        # at c=2, d[1]=2 because it would decode to forbidden plaintext F.
        result = scan_cipher([0, 2])
        self.assertEqual(result["final_clocks"], [1])
        self.assertEqual(result["terminal_path_count_capped"], 1)
        self.assertEqual(result["exception_edges"], 1)
        self.assertEqual(result["ordinary_edges"], 2)

    def test_nonzero_cipher_that_decodes_to_f_is_dead(self):
        result = scan_cipher([1])
        self.assertEqual(result["final_state_count"], 0)
        self.assertEqual(result["first_dead_position"], 0)

    def test_page_reset_and_continuity_are_distinct_inputs(self):
        deltas = prime_deltas(2)
        first = scan_cipher([2], deltas=deltas)
        second_continuous = scan_cipher([1], start_clocks=first["final_clocks"], deltas=deltas)
        second_reset = scan_cipher([1], start_clocks=(0,), deltas=deltas)
        self.assertEqual(second_continuous["final_clocks"], [2])
        self.assertEqual(second_reset["final_state_count"], 0)

    def test_worker_rejects_answer_and_seed_fields(self):
        public = {
            "schema": 1,
            "hypothesis": "H007-v1",
            "continuities": ["continuous", "page_reset"],
            "jobs": [{"id": "toy", "pages": [{"page": "toy", "cipher": [0]}]}],
        }
        for field in ("expected", "seed"):
            candidate = dict(public)
            candidate[field] = [1]
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(ROOT / "scripts/attempt3_worker.py")],
                input=json.dumps(candidate),
                capture_output=True,
                text=True,
                encoding="utf8",
                cwd=ROOT,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unexpected public fields", result.stderr)


if __name__ == "__main__":
    unittest.main()
