from contextlib import contextmanager
from itertools import permutations
import json
import math
from pathlib import Path
import sys
import shutil
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.attempt1_stats import analyze, permutation_moments


@contextmanager
def scratch_dir():
    # Python 3.12's mode-0700 TemporaryDirectory ACL excludes the restricted
    # Windows test token. Inherit the workspace ACL using ordinary mkdir.
    directory = ROOT / (".attempt1-stats-test-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if not directory.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError("Test cleanup path escaped the workspace")
        shutil.rmtree(directory)


class Attempt1StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.weights = [math.log((i+1)/435) for i in range(29)]

    def test_exact_moments_match_all_permutations_including_duplicates(self):
        for cipher, delta in (([0, 1, 2, 3], [0, 1, 3, 5]),
                              ([0, 0, 1, 2], [2, 2, 3, 8]),
                              ([4, 2], [5, 0])):
            values = [math.fsum(self.weights[(c-d) % 29] for c, d in zip(p, delta))
                      for p in permutations(cipher)]
            expected_mean = math.fsum(values) / len(values)
            expected_variance = math.fsum((v-expected_mean)**2 for v in values) / len(values)
            mean, variance = permutation_moments(cipher, delta, self.weights)
            self.assertAlmostEqual(mean, expected_mean, places=12)
            self.assertAlmostEqual(variance, expected_variance, places=12)

    def test_invariant_delta_is_nondiscriminating_and_cannot_be_lead(self):
        cipher, delta = [0, 1, 2, 3], [2, 2, 2, 2]
        plain = [(c-d) % 29 for c, d in zip(cipher, delta)]
        _, variance = permutation_moments(cipher, delta, self.weights)
        self.assertEqual(variance, 0)
        with scratch_dir() as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT.resolve()))
            result = analyze([dict(page="test", cipher=cipher)],
                             [dict(page="test", methods=["constant"], delta=delta,
                                   plaintext=plain, log_likelihood=math.fsum(self.weights[c] for c in plain))],
                             self.weights, directory, permutations=19)
            self.assertEqual(result["rows"][0]["z"], 0)
            self.assertEqual(result["rows"][0]["p_adjusted"], 1)
            self.assertEqual(result["rows"][0]["status"], "negative")
            self.assertEqual(result["lead_count"], 0)

    def test_control_correlations_maxima_plus_one_and_replay(self):
        cipher = [0, 2, 2, 5, 9]
        deltas = [[0, 1, 2, 3, 4], [1, 1, 3, 3, 5]]
        candidates = []
        for index, delta in enumerate(deltas):
            plain = [(c-d) % 29 for c, d in zip(cipher, delta)]
            candidates.append(dict(page="test", methods=[f"clock{index}"], delta=delta,
                                   plaintext=plain, log_likelihood=math.fsum(self.weights[c] for c in plain)))
        with scratch_dir() as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT.resolve()))
            output = []
            for name in ("first", "replay"):
                summary = analyze([dict(page="test", cipher=cipher)], candidates, self.weights,
                                  Path(directory) / name, permutations=19, control_seed=7)
                output.append(json.loads(Path(summary["control_scores_path"]).read_text(encoding="utf8")))
            self.assertEqual(output[0]["replicates"], output[1]["replicates"])
            # Independently enumerate joint score pairs. Every replicate must
            # belong to one shared page permutation, not two unrelated draws.
            possible = {tuple(round(math.fsum(self.weights[(c-d) % 29]
                                               for c, d in zip(p, delta)), 12)
                              for delta in deltas) for p in permutations(cipher)}
            for row in output[0]["replicates"]:
                self.assertIn(tuple(round(v, 12) for v in row["log_likelihood"]), possible)
                self.assertEqual(row["max_z"], max(row["z"]))
            for row in summary["rows"]:
                count = sum(maximum >= row["z"] for maximum in output[0]["max_z"])
                self.assertEqual(row["p_adjusted"], (1+count)/20)

    def test_single_rune_and_constant_weights_have_zero_variance(self):
        self.assertEqual(permutation_moments([1], [2], self.weights)[1], 0)
        self.assertEqual(permutation_moments([1, 2, 3], [2, 5, 1], [-3.0]*29)[1], 0)

    def test_timeout_preserves_completed_control_replicates(self):
        cipher, delta = [0, 1, 2], [0, 2, 3]
        plain = [(c-d) % 29 for c, d in zip(cipher, delta)]
        candidate = dict(page="test", methods=["clock"], delta=delta, plaintext=plain,
                         log_likelihood=math.fsum(self.weights[c] for c in plain))
        with scratch_dir() as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT.resolve()))
            with patch("lp_lab.attempt1_stats.time.monotonic", side_effect=[0, 0, 2, 2]):
                with self.assertRaisesRegex(TimeoutError, "1/19"):
                    analyze([dict(page="test", cipher=cipher)], [candidate], self.weights,
                            directory, permutations=19, timeout_seconds=1)
            partial = json.loads((Path(directory)/"control-scores.json").read_text(encoding="utf8"))
            self.assertEqual(partial["metadata"]["status"], "timeout")
            self.assertEqual(partial["metadata"]["completed_control_replicates"], 1)
            self.assertEqual(len(partial["replicates"]), 1)


if __name__ == "__main__":
    unittest.main()
