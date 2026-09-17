import copy
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.runes import RUNES
import attempt18_row_edge_v1 as runner
import attempt18_row_edge_worker_v1 as worker


class RowEdgeTests(unittest.TestCase):
    def test_slash_rows_ignore_crlf_and_hard_barriers(self):
        raw = f"\r\n{RUNES[1]}{RUNES[2]}-{RUNES[3]}/{RUNES[4]}A{RUNES[5]}/{RUNES[6]}//"
        rows = runner.derive_rows_for_verifier(raw)
        self.assertEqual([row["values"] for row in rows], [[1, 2, 3], [4, 5], [6], []])
        self.assertEqual([row["group"] for row in rows], [0, None, 1, None])
        metrics = runner.verifier_g(rows)
        self.assertEqual(metrics["eligible_row_count"], 1)
        self.assertEqual(metrics["edge_count"], 2)
        self.assertEqual(metrics["interior_count"], 1)

    def test_worker_and_independent_verifier_agree(self):
        raw = runner.raw_from_rows([[0, 1, 2, 3], [3, 2, 1], [4, 5]])
        job = dict(id="row-edge-unit", pages=[dict(page="row-edge-page", raw=raw)])
        actual = worker.run_job(job)["pages"][0]
        expected_rows = runner.derive_rows_for_verifier(raw)
        expected = runner.verifier_g(expected_rows)
        self.assertEqual(actual["rows"], expected_rows)
        for field in ("eligible_row_count", "edge_count", "interior_count", "g_stat"):
            self.assertEqual(actual[field], expected[field])

    def test_g_statistic_detects_fixed_edge_role_but_not_position_independent_class(self):
        edge_rows = runner.derive_rows_for_verifier(
            runner.raw_from_rows([[0, 1, 1, 1, 0] for _ in range(12)])
        )
        uniform_rows = runner.derive_rows_for_verifier(
            runner.raw_from_rows([[0, 1, 0, 1, 0] for _ in range(12)])
        )
        self.assertGreater(runner.verifier_g(edge_rows)["g_stat"], runner.verifier_g(uniform_rows)["g_stat"])

    def test_synthetic_gate_and_three_negative_classes_are_fixed(self):
        jobs, answers, labels = runner.synthetic_gate()
        self.assertEqual(len(jobs), 119)
        self.assertEqual(sum(label == "positive" for label in labels.values()), 20)
        self.assertEqual(sum(label == "negative_uniform" for label in labels.values()), 33)
        self.assertEqual(sum(label == "negative_row_heterogeneous" for label in labels.values()), 33)
        self.assertEqual(sum(label == "negative_fixed_seven" for label in labels.values()), 33)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        gate = runner.gate_result(output, answers)
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["positive_exact"], 20)
        self.assertEqual(gate["positive_score_passes"], 20)
        self.assertEqual(gate["negative_false_accepts"], 0)
        self.assertTrue(runner.gate_allows_lp2(gate))

    def test_gate_failure_summary_forbids_second_stage(self):
        summary = runner.build_gate_failure_summary(
            {"status": "failed", "positive_score_passes": 17, "negative_false_accepts": 0},
            "passed",
        )
        self.assertEqual(summary["lp2_status"], "not_dispatched_gate_failed")
        self.assertEqual(summary["coverage"]["pages"], 0)
        self.assertEqual(summary["controls_completed"], 0)

    def test_mutated_worker_row_is_rejected(self):
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

    def test_rotation_preserves_values_and_circular_adjacency(self):
        rows = runner.derive_rows_for_verifier(runner.raw_from_rows([[1, 2, 3, 4], [5, 6]]))
        rotated = runner.random_rotate_rows(rows, random.Random(17))
        for before, after in zip(rows, rotated):
            self.assertEqual(sorted(before["values"]), sorted(after["values"]))
            if len(before["values"]) > 1:
                before_edges = {
                    (before["values"][index], before["values"][(index + 1) % len(before["values"])] )
                    for index in range(len(before["values"]))
                }
                after_edges = {
                    (after["values"][index], after["values"][(index + 1) % len(after["values"])] )
                    for index in range(len(after["values"]))
                }
                self.assertEqual(before_edges, after_edges)


if __name__ == "__main__":
    unittest.main()
