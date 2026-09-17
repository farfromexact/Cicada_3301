import copy
import json
from itertools import product
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from lp_lab.periodic_f_state_v2 import DEFAULT_KEY, scan_page
import attempt13_periodic_f_state_v2 as runner
import attempt13_worker_v2 as worker


class PeriodicFStateV2Tests(unittest.TestCase):
    def test_scan_matches_untruncated_forward_oracle_for_all_short_inputs(self):
        # Build the oracle by enumerating plaintext p=0..28.  Counts stay
        # untruncated until the final comparison, so this is not a copy of the
        # worker's inverse branch or its intermediate cap.
        forward = {}
        for phase, delta in enumerate(DEFAULT_KEY):
            for cipher_value in range(29):
                forward[(phase, cipher_value)] = []
            for plaintext in range(29):
                if plaintext == 0:
                    cipher_value = 0
                    next_phase = phase
                else:
                    cipher_value = (plaintext + delta) % 29
                    next_phase = (phase + 1) % len(DEFAULT_KEY)
                forward[(phase, cipher_value)].append(next_phase)

        def oracle(cipher, start_phase):
            ways = {start_phase: 1}
            for cipher_value in cipher:
                next_ways = {}
                for phase, count in ways.items():
                    for next_phase in forward[(phase, cipher_value)]:
                        next_ways[next_phase] = next_ways.get(next_phase, 0) + count
                ways = next_ways
            return [
                [phase, min(2, count)] for phase, count in sorted(ways.items())
            ]

        checked = 0
        for start_phase in range(len(DEFAULT_KEY)):
            for length in range(4):
                for cipher in product(range(29), repeat=length):
                    actual = scan_page(
                        cipher,
                        start_phases=(start_phase,),
                        initial_ways={start_phase: 1},
                    )["final_path_counts"]
                    self.assertEqual(
                        actual,
                        oracle(cipher, start_phase),
                        msg=f"start={start_phase}, cipher={cipher}",
                    )
                    checked += 1
        self.assertEqual(checked, 13 * (1 + 29 + 29**2 + 29**3))

    def test_direct_table_covers_every_phase_cipher_cell_and_forward_edges(self):
        table = runner.direct_transition_table()
        self.assertEqual(len(table), len(DEFAULT_KEY) * 29)
        for phase, delta in enumerate(DEFAULT_KEY):
            for cipher_value in range(29):
                self.assertIn((phase, cipher_value), table)
            for plaintext in range(29):
                if plaintext == 0:
                    cipher_value = 0
                    expected = (phase, "exception")
                else:
                    cipher_value = (plaintext + delta) % 29
                    expected = ((phase + 1) % len(DEFAULT_KEY), "ordinary")
                self.assertIn(expected, table[(phase, cipher_value)])
            if delta != 0:
                self.assertEqual(table[(phase, delta)], ())

    def test_ciphertext_f_keeps_exception_and_ordinary_paths(self):
        result = scan_page([1, 0])
        self.assertEqual(result["final_phases"], [1, 2])
        self.assertEqual(result["final_path_counts"], [[1, 1], [2, 1]])
        self.assertEqual(result["terminal_path_count_capped"], 2)
        self.assertEqual(result["model_status"], "compatible")

    def test_nonzero_cipher_that_decodes_to_f_is_dead(self):
        result = scan_page([1, DEFAULT_KEY[1]])
        self.assertEqual(result["model_status"], "dead")
        self.assertEqual(result["final_state_count"], 0)
        self.assertEqual(result["first_dead_position"], 1)
        self.assertEqual(result["legal_prefix_length"], 1)

    def test_cross_page_path_counts_match_concatenated_scan(self):
        first = [1, 0, 0]
        second = [10, 1]
        first_result = scan_page(first)
        self.assertEqual(first_result["final_path_counts"], [[1, 1], [2, 2], [3, 1]])
        carried = {phase: count for phase, count in first_result["final_path_counts"]}
        split_result = scan_page(
            second,
            start_phases=first_result["final_phases"],
            initial_ways=carried,
        )
        whole_result = scan_page(first + second)
        self.assertEqual(split_result["final_path_counts"], [[4, 2]])
        self.assertEqual(split_result["final_path_counts"], whole_result["final_path_counts"])
        reset_result = scan_page(second)
        self.assertEqual(reset_result["final_path_counts"], [[2, 1]])

    def test_empty_continuous_state_is_not_reached(self):
        result = worker.run_job(
            dict(
                id="classification-regression",
                branch="continuous",
                pages=[
                    dict(page="dead", cipher=[1, DEFAULT_KEY[1]]),
                    dict(page="downstream", cipher=[1]),
                ],
            )
        )
        self.assertEqual(result["pages"][0]["model_status"], "dead")
        self.assertEqual(result["pages"][1]["model_status"], "not_reached")
        self.assertIsNone(result["pages"][1]["legal_prefix_ratio"])
        self.assertEqual(result["pages"][1]["upstream_dead_page"], "dead")
        self.assertEqual(result["pages"][1]["ordinary_edges"], 0)

    def test_positive_verification_is_complete_and_mutation_fails(self):
        heldout = runner.encode_text(
            (ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8")
        )
        synthetic_jobs, answers = runner.synthetic_controls(heldout)
        public = dict(schema=1, hypothesis=runner.HYPOTHESIS, jobs=synthetic_jobs)
        output = dict(
            status="completed",
            read_guard_probe_passed=True,
            jobs=[worker.run_job(job) for job in synthetic_jobs],
        )
        verification = runner.verify_worker(public, output, answers)
        self.assertEqual(
            {row["job"] for row in verification["positive_path_checks"]},
            runner.EXPECTED_POSITIVE_JOB_IDS,
        )
        mutated = copy.deepcopy(answers)
        job_id = sorted(runner.EXPECTED_POSITIVE_JOB_IDS)[0]
        mutated[job_id]["expected_terminal_phase"] = (
            mutated[job_id]["expected_terminal_phase"] + 1
        ) % len(DEFAULT_KEY)
        with self.assertRaises(ValueError):
            runner.verify_worker(public, output, mutated)

    def test_zero_preserving_shuffle_keeps_multiset_and_positions(self):
        values = [0, 1, 2, 0, 3, 4]
        shuffled = runner.randomize_preserving_zero_positions(values, __import__("random").Random(7))
        self.assertEqual(
            [i for i, value in enumerate(values) if value == 0],
            [i for i, value in enumerate(shuffled) if value == 0],
        )
        self.assertEqual(
            sorted(value for value in values if value != 0),
            sorted(value for value in shuffled if value != 0),
        )


if __name__ == "__main__":
    unittest.main()
