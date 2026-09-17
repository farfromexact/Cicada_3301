import copy
from pathlib import Path
import random
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.runes import RUNES
import attempt17_snake_row_v1 as runner
import attempt17_snake_row_worker_v1 as worker


class SnakeRowTests(unittest.TestCase):
    def test_snake_mask_resets_at_short_rows_and_hard_segments(self):
        raw = f"{RUNES[1]}{RUNES[2]}/{RUNES[3]}{RUNES[4]}/{RUNES[5]}/A{RUNES[6]}{RUNES[7]}/{RUNES[8]}{RUNES[9]}/"
        rows = runner.derive_rows_for_verifier(raw)
        self.assertEqual(runner.verifier_snake_mask(rows), [False, True, False, False, True])

    def test_directed_bigrams_are_not_circular_and_reverse_changes_direction(self):
        rows = runner.derive_rows_for_verifier(runner.raw_from_rows([[1, 2, 3], [1, 2, 3]]))
        original, pairs = runner.verifier_score(rows, [False, False])
        reversed_score, reversed_pairs = runner.verifier_score(rows, [False, True])
        self.assertEqual(pairs, reversed_pairs)
        self.assertEqual(original, 0.5)
        self.assertEqual(reversed_score, 0.0)

    def test_worker_and_verifier_agree_on_page_metrics(self):
        raw = runner.raw_from_rows([[0, 1, 2, 3], [3, 2, 1], [0, 1, 2]])
        job = dict(id="snake-unit", pages=[dict(page="snake-page", raw=raw)])
        actual = worker.run_job(job)["pages"][0]
        rows = runner.derive_rows_for_verifier(raw)
        expected = runner.verifier_metrics(rows)
        self.assertEqual(actual["rows"], rows)
        for field in ("original_score", "snake_score", "delta", "pair_count"):
            self.assertEqual(actual[field], expected[field])

    def test_synthetic_gate_has_three_fixed_negative_classes_and_exposes_failure(self):
        jobs, answers, labels = runner.synthetic_gate()
        self.assertEqual(len(jobs), 119)
        self.assertEqual(sum(kind == "positive" for kind in labels.values()), 20)
        self.assertEqual(sum(kind == "negative_random_direction" for kind in labels.values()), 33)
        self.assertEqual(sum(kind == "negative_all_forward" for kind in labels.values()), 33)
        self.assertEqual(sum(kind == "negative_uniform_random" for kind in labels.values()), 33)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in jobs],
        )
        gate = runner.gate_result(output, answers)
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(gate["positive_score_passes"], 20)
        self.assertEqual(gate["negative_false_accepts"], 2)
        self.assertEqual(gate["negative_class_false_accepts"], {
            "negative_all_forward": 0,
            "negative_random_direction": 2,
            "negative_uniform_random": 0,
        })

    def test_random_row_reversal_preserves_values_and_undirected_edges(self):
        rows = runner.derive_rows_for_verifier(runner.raw_from_rows([[1, 2, 3, 4], [4, 5, 6]]))
        reversed_rows = runner.random_orient_rows(rows, random.Random(19))
        for before, after in zip(rows, reversed_rows):
            self.assertEqual(sorted(before["values"]), sorted(after["values"]))
            before_edges = {
                frozenset((left, right))
                for left, right in zip(before["values"], before["values"][1:])
            }
            after_edges = {
                frozenset((left, right))
                for left, right in zip(after["values"], after["values"][1:])
            }
            self.assertEqual(before_edges, after_edges)

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


if __name__ == "__main__":
    unittest.main()
