import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.feedback import cumulative_encrypt, difference_page
import attempt14_feedback_v1 as runner
import attempt14_feedback_worker_v1 as worker


class FeedbackTests(unittest.TestCase):
    def test_difference_and_cumulative_are_exact_inverses(self):
        plaintext = [0, 0, 1, 28, 3, 0, 7]
        cipher = cumulative_encrypt(plaintext)
        self.assertEqual(cipher, [0, 0, 1, 0, 3, 3, 10])
        self.assertEqual(difference_page(cipher), plaintext)

    def test_first_rune_and_adjacent_equal_ciphertext_are_retained(self):
        cipher = [0, 0, 1, 0]
        self.assertEqual(runner.independent_difference(cipher), [0, 0, 1, 28])
        self.assertEqual(
            worker.run_job(dict(id="edge", pages=[dict(page="p", cipher=cipher)]))["pages"][0]["decoded_indices"],
            [0, 0, 1, 28],
        )

    def test_internal_ciphertext_perturbation_is_local(self):
        cipher = [3, 7, 9, 2, 8]
        delta = 5
        changed = list(cipher)
        changed[2] = (changed[2] + delta) % 29
        before = runner.independent_difference(cipher)
        after = runner.independent_difference(changed)
        expected_delta = [0, 0, delta, -delta, 0]
        self.assertEqual(
            [(new - old) % 29 for old, new in zip(before, after)],
            [value % 29 for value in expected_delta],
        )

    def test_positive_verification_is_complete_and_output_mutation_fails(self):
        heldout = runner.encode_text(
            (ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8")
        )
        jobs, answers = runner.synthetic_controls(heldout)
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(
            {row["job"] for row in verification["positive_path_checks"]},
            runner.EXPECTED_POSITIVE_JOB_IDS,
        )
        mutated = copy.deepcopy(output)
        mutated["jobs"][0]["pages"][0]["decoded_indices"][5] = (
            mutated["jobs"][0]["pages"][0]["decoded_indices"][5] + 1
        ) % 29
        with self.assertRaises(ValueError):
            runner.verify_worker(public, mutated, answers)

    def test_positive_synthetic_plaintexts_include_first_f_and_boundary_cases(self):
        heldout = runner.encode_text(
            (ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8")
        )
        _, answers = runner.synthetic_controls(heldout)
        for answer in answers.values():
            self.assertEqual(answer["plaintext"][0], 0)
            self.assertEqual(answer["plaintext"][1], 0)
            self.assertEqual(answer["cipher"][0], answer["cipher"][1])


if __name__ == "__main__":
    unittest.main()
