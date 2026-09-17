import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.projection import SUBGROUP, fourth_power
import attempt15_projection_v2 as runner
import attempt15_projection_worker_v2 as worker


class ProjectionTests(unittest.TestCase):
    def test_projection_matches_independent_repeated_multiplication(self):
        values = list(range(29))
        expected = [((value * value) % 29) ** 2 % 29 for value in values]
        self.assertEqual(fourth_power(values), expected)
        self.assertEqual(runner.independent_projection(values), expected)
        self.assertEqual(len(runner.PROJECTED_CLASSES), 8)
        self.assertEqual(set(runner.PROJECTED_CLASSES), set(expected))
        self.assertTrue(all(runner.PREIMAGES[value] for value in runner.PROJECTED_CLASSES))

    def test_subgroup_invariance_covers_zero_and_all_runes(self):
        for multiplier in SUBGROUP:
            for value in range(29):
                self.assertEqual(
                    runner.repeated_fourth((multiplier * value) % 29),
                    runner.repeated_fourth(value),
                )

    def test_fixed_power_gate_pattern_clears_preregistered_threshold(self):
        projected = runner.make_run_pattern(1)
        cipher, _ = runner.subgroup_encrypt(
            runner.lift_projection(projected), __import__("random").Random(7)
        )
        self.assertEqual(runner.independent_projection(cipher), projected)
        self.assertGreaterEqual(runner.projection_score(cipher), runner.GATE_THRESHOLD)

    def test_worker_projection_matches_independent_verifier(self):
        cipher = [0, 1, 12, 17, 28, 2, 4, 7]
        job = dict(id="unit", pages=[dict(page="unit-page", cipher=cipher)])
        output = worker.run_job(job)
        self.assertEqual(
            output["pages"][0]["projected_indices"],
            runner.independent_projection(cipher),
        )

    def test_synthetic_gate_is_complete_and_passes(self):
        jobs, answers, labels = runner.synthetic_gate()
        self.assertEqual(len(jobs), 40)
        self.assertEqual(set(labels), {job["id"] for job in jobs})
        for index in range(1, runner.GATE_POSITIVE_COUNT + 1):
            positive = answers[f"gate-positive-{index:02d}"]["projected"]
            negative = answers[f"gate-negative-{index:02d}"]["projected"]
            self.assertEqual(
                [position for position, value in enumerate(positive) if value == 0],
                [position for position, value in enumerate(negative) if value == 0],
            )
            self.assertEqual(
                sorted(value for value in positive if value != 0),
                sorted(value for value in negative if value != 0),
            )
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(verification["page_checks"], 40)
        gate = runner.gate_result(output, answers)
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["positive_score_passes"], 20)
        self.assertEqual(gate["negative_false_accepts"], 0)

    def test_failed_gate_cannot_publish_lp2_statistics(self):
        failed = dict(status="failed", positive_score_passes=0, negative_false_accepts=20)
        self.assertFalse(runner.gate_allows_lp2(failed))
        summary = runner.build_gate_failure_summary(failed, "passed")
        self.assertEqual(summary["status"], "inconclusive")
        self.assertEqual(summary["lp2_status"], "not_run_gate_failed")
        self.assertEqual(summary["coverage"]["pages"], 0)
        self.assertEqual(summary["leads"], [])

    def test_mutated_projection_output_is_rejected(self):
        jobs, answers, _ = runner.synthetic_gate()
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        mutated = copy.deepcopy(output)
        mutated["jobs"][0]["pages"][0]["projected_indices"][3] = (
            mutated["jobs"][0]["pages"][0]["projected_indices"][3] + 1
        ) % 29
        with self.assertRaises(ValueError):
            runner.verify_worker(public, mutated, answers)


if __name__ == "__main__":
    unittest.main()
