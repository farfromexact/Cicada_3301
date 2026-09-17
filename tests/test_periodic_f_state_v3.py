from pathlib import Path
import copy
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import attempt13_periodic_f_state_v3 as runner
import attempt13_worker_v3 as worker


class PeriodicFStateV3Tests(unittest.TestCase):
    def test_two_page_positive_jobs_cover_both_branches_and_verify(self):
        heldout = runner.base.encode_text(
            (ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8")
        )
        jobs, answers = runner.synthetic_controls(heldout)
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.base.run_job(job) for job in jobs],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(verification["status"], "passed")
        self.assertEqual(len(verification["positive_path_checks"]), 4)
        self.assertEqual(len(verification["positive_page_endpoint_checks"]), 8)
        self.assertTrue(
            all(
                row["endpoint_phase"] != 0
                for row in verification["positive_page_endpoint_checks"]
            )
        )
        self.assertTrue(
            all(
                len(job["pages"]) == 2
                for job in jobs
                if job["id"] in runner.EXPECTED_POSITIVE_JOB_IDS
            )
        )
        self.assertEqual(
            {row["job"] for row in verification["positive_path_checks"]},
            runner.EXPECTED_POSITIVE_JOB_IDS,
        )

    def test_v3_mutating_a_second_page_endpoint_fails(self):
        heldout = runner.base.encode_text(
            (ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8")
        )
        jobs, answers = runner.synthetic_controls(heldout)
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.base.run_job(job) for job in jobs],
        )
        mutated_answers = copy.deepcopy(answers)
        job_id = "synthetic-positive-1-continuous"
        mutated_answers[job_id]["expected_page_phases"][1] = (
            mutated_answers[job_id]["expected_page_phases"][1] + 1
        ) % len(runner.base.DEFAULT_KEY)
        with self.assertRaises(ValueError):
            runner.verify_worker(public, output, mutated_answers)

    def test_v3_public_worker_rejects_v2_hypothesis(self):
        with self.assertRaises(ValueError):
            worker.base.validate_public(
                {"schema": 1, "hypothesis": "H016-periodic-plaintext-F-state-v2", "jobs": []}
            )


if __name__ == "__main__":
    unittest.main()
