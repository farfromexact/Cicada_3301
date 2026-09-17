import unittest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import attempt21_bm_v3 as continuation


class R015BmV3ContractTests(unittest.TestCase):
    def test_worker_contract_checks_result_order_before_normalization(self):
        job = {"id": "job-0", "cipher": [0]}
        output = {
            "status": "completed",
            "read_guard_probe_passed": True,
            "view_names": list(continuation.base.VIEW_NAMES),
            "results": [
                {
                    "id": job["id"],
                    "sequence_length": 1,
                    "views": {name: {} for name in continuation.base.VIEW_NAMES},
                }
            ],
        }
        continuation.assert_worker_result_contract(output, [job], "unit")
        output["results"].append(dict(output["results"][0]))
        with self.assertRaises(ValueError):
            continuation.assert_worker_result_contract(output, [job], "duplicate")

    def test_canonical_resume_comparison_keeps_bool_and_integer_distinct(self):
        self.assertNotEqual(continuation.canonical({"ok": True}), continuation.canonical({"ok": 1}))

    def test_v3_contract_is_four_views_and_exact_resume_count(self):
        self.assertEqual(continuation.EXPECTED_VIEW_NAMES, list(continuation.base.VIEW_NAMES))
        self.assertEqual(continuation.RESUME_COUNT, 200)
        self.assertEqual(continuation.CONTROL_COUNT, 999)
        self.assertEqual(continuation.ALPHA, 0.01 / 3.0)


if __name__ == "__main__":
    unittest.main()
