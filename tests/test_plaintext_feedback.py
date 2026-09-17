import copy
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import attempt19_plaintext_feedback_v1 as runner
import attempt19_plaintext_feedback_worker_v1 as worker


class PlaintextFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.heldout = runner.encode_text(
            runner.HELDOUT_PATH.read_text(encoding="utf8")
        )
        cls.training, cls.training_counts, cls.weights = runner.scorer_basis()

    def test_recurrence_roundtrip_includes_zero_boundary(self):
        plaintext = [0, 0, 1, 28, 4, 0, 7, 2]
        cipher = runner.independent_encrypt(plaintext)
        self.assertEqual(runner.independent_decode(cipher), plaintext)
        self.assertEqual(worker.decode_plaintext_feedback(cipher), plaintext)

    def test_worker_and_verifier_agree_on_public_job(self):
        plaintext = [0, 3, 3, 1, 28, 5]
        cipher = runner.independent_encrypt(plaintext)
        job = dict(id="plaintext-feedback-unit", pages=[dict(page="unit-page", cipher=cipher)])
        actual = worker.run_job(job)
        expected = runner.independent_job(job)
        self.assertEqual(actual, expected)

    def test_public_worker_rejects_answer_and_seed_fields(self):
        with self.assertRaises(ValueError):
            worker.validate_public(
                {
                    "schema": 1,
                    "hypothesis": runner.HYPOTHESIS,
                    "seed": runner.CONTROL_SEED,
                    "jobs": [],
                }
            )

    def test_gate_is_separate_from_lp2_public_job(self):
        gate_public, answers, labels = runner.build_gate_public(self.heldout, self.weights)
        self.assertEqual(len(gate_public["jobs"]), 119)
        self.assertTrue(all(job["id"].startswith("gate-") for job in gate_public["jobs"]))
        lp2 = runner.build_lp2_public([dict(page="LP2/0", cipher=[1, 2, 3])])
        self.assertEqual([job["id"] for job in lp2["jobs"]], ["unsolved-page-reset"])
        self.assertNotIn("unsolved-page-reset", [job["id"] for job in gate_public["jobs"]])
        self.assertEqual(len(answers), 20)
        self.assertEqual(sum(label == "positive" for label in labels.values()), 20)

    def test_synthetic_gate_passes_all_three_negative_classes(self):
        public, answers, labels = runner.build_gate_public(self.heldout, self.weights)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in public["jobs"]],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(verification["status"], "passed")
        self.assertEqual(len(verification["positive_path_checks"]), 20)
        gate = runner.gate_result(public, output, answers, labels, self.weights)
        self.assertEqual(gate["status"], "passed")
        self.assertEqual(gate["positive_exact"], 20)
        self.assertEqual(gate["positive_score_passes"], 20)
        self.assertEqual(gate["negative_false_accepts"], 0)
        self.assertEqual(
            gate["negative_class_false_accepts"],
            {
                "negative_shuffled_plaintext": 0,
                "negative_uniform_ciphertext": 0,
                "negative_wrong_h017_cumulative_feedback": 0,
            },
        )
        self.assertTrue(runner.gate_allows_lp2(gate))

    def test_bigram_score_is_order_sensitive(self):
        plaintext = runner.positive_plaintext(self.heldout, 0, runner.GATE_LENGTHS[0])
        shuffled = list(plaintext)
        random.Random(91).shuffle(shuffled)
        self.assertGreater(
            runner.score(plaintext, self.weights),
            runner.score(shuffled, self.weights),
        )

    def test_mutated_worker_output_is_rejected(self):
        public, answers, _ = runner.build_gate_public(self.heldout, self.weights)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in public["jobs"]],
        )
        runner.verify_worker(public, output, answers)
        mutated = copy.deepcopy(output)
        mutated["jobs"][0]["pages"][0]["decoded_indices"][0] = 28
        with self.assertRaises(ValueError):
            runner.verify_worker(public, mutated, answers)

    def test_ciphertext_permutation_preserves_multiset(self):
        plaintext = [0, 1, 2, 2, 1, 0, 28]
        cipher = runner.independent_encrypt(plaintext)
        shuffled = list(cipher)
        random.Random(11).shuffle(shuffled)
        self.assertEqual(sorted(cipher), sorted(shuffled))
        self.assertNotEqual(runner.independent_decode(shuffled), plaintext)


if __name__ == "__main__":
    unittest.main()
