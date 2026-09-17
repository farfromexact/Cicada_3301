import copy
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.runes import RUNES
import attempt16_row_geometry_v1 as runner
import attempt16_row_geometry_worker_v1 as worker


class RowGeometryTests(unittest.TestCase):
    def test_slash_rows_ignore_crlf_and_compare_common_left_ordinals(self):
        raw = f"\r\n{RUNES[1]}{RUNES[2]}-{RUNES[3]}/\r\n{RUNES[1]}{RUNES[4]}/\n"
        rows = runner.derive_rows_for_verifier(raw)
        self.assertEqual([row["values"] for row in rows], [[1, 2, 3], [1, 4]])
        self.assertEqual([row["group"] for row in rows], [0, 0])
        self.assertEqual(runner.verifier_metrics(rows), {"equal_count": 1, "comparison_count": 2, "score": 0.5})

    def test_empty_and_hard_rows_are_barriers(self):
        raw = f"{RUNES[1]}/{RUNES[2]}//A{RUNES[3]}/{RUNES[4]}/"
        rows = runner.derive_rows_for_verifier(raw)
        self.assertEqual([row["values"] for row in rows], [[1], [2], [], [3], [4]])
        self.assertEqual([row["group"] for row in rows], [0, 0, None, 1, 1])
        self.assertEqual(runner.verifier_metrics(rows)["comparison_count"], 2)

    def test_worker_and_verifier_agree_on_raw_rows(self):
        raw = runner.raw_from_rows([[1, 2, 3], [1, 4], [5, 6, 7, 8]])
        job = dict(id="row-unit", pages=[dict(page="row-page", raw=raw)])
        actual = worker.run_job(job)
        rows = runner.derive_rows_for_verifier(raw)
        expected = runner.verifier_metrics(rows)
        self.assertEqual(actual["pages"][0]["rows"], rows)
        self.assertEqual(actual["pages"][0]["equal_count"], expected["equal_count"])
        self.assertEqual(actual["pages"][0]["comparison_count"], expected["comparison_count"])
        self.assertEqual(actual["pages"][0]["score"], expected["score"])

    def test_gate_has_fixed_positive_and_difficult_negative_classes(self):
        jobs, answers, labels = runner.synthetic_gate()
        self.assertEqual(len(jobs), 119)
        self.assertEqual(sum(kind == "positive" for kind in labels.values()), 20)
        self.assertEqual(sum(kind == "negative_hard" for kind in labels.values()), 33)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        gate = runner.gate_result(output, answers)
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["positive_score_passes"], 20)
        self.assertEqual(gate["negative_false_accepts"], 0)
        self.assertEqual(gate["hard_negative_false_accepts"], 0)

    def test_row_rotation_preserves_multiset_and_circular_adjacency(self):
        rows = runner.derive_rows_for_verifier(runner.raw_from_rows([[1, 2, 3, 4], [5, 6]]))
        rotated = runner.rotate_rows(rows, random.Random(17))
        for before, after in zip(rows, rotated):
            self.assertEqual(len(before["values"]), len(after["values"]))
            self.assertEqual(sorted(before["values"]), sorted(after["values"]))
            if len(before["values"]) > 1:
                before_edges = {
                    (before["values"][i], before["values"][(i + 1) % len(before["values"])])
                    for i in range(len(before["values"]))
                }
                after_edges = {
                    (after["values"][i], after["values"][(i + 1) % len(after["values"])])
                    for i in range(len(after["values"]))
                }
                self.assertEqual(before_edges, after_edges)

    def test_mutated_worker_row_is_rejected_by_independent_verifier(self):
        jobs, answers, _ = runner.synthetic_gate()
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(len(verification["positive_row_checks"]), 20)
        mutated = copy.deepcopy(output)
        mutated["jobs"][0]["pages"][0]["rows"][0]["values"][0] = 28
        with self.assertRaises(ValueError):
            runner.verify_worker(public, mutated, answers)


if __name__ == "__main__":
    unittest.main()
