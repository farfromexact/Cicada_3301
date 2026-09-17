from collections import Counter
import itertools
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.structure_stats import FAMILY_ALPHA, metrics, randomized_scan


def page(values, groups=None, segments=None, hyphens=None, eligible=None):
    n = len(values)
    return dict(indices=values, groups=groups if groups is not None else [0] * n,
                segments=segments if segments is not None else [[0, n]],
                hyphen_mask=hyphens if hyphens is not None else [False] * n,
                boundary_eligible=eligible if eligible is not None else [True] * n)


def manual_counts(pages):
    lag_counts, boundary = [], []
    occurrences = []
    for p in pages:
        x, g = p["indices"], p["groups"]
        lag_counts.extend(sum(x[i] == x[i + lag] and g[i] == g[i + lag]
                              for i in range(max(0, len(x) - lag))) for lag in range(1, 30))
        observations = Counter((x[i], int(p["hyphen_mask"][i])) for i in range(len(x))
                               if p["boundary_eligible"][i])
        size = sum(observations.values())
        row = Counter()
        col = Counter()
        for (rune, flag), count in observations.items():
            row[rune] += count
            col[flag] += count
        boundary.append(2 * sum(count * math.log(count * size / (row[rune] * col[flag]))
                                for (rune, flag), count in observations.items()))
        occurrences.append([tuple(x[i:i + 4]) for i in range(len(x) - 3) if g[i] == g[i + 3]])
    pairs = sum(left == right for i in range(len(pages)) for j in range(i + 1, len(pages))
                for left in occurrences[i] for right in occurrences[j])
    return lag_counts, boundary, pairs


class StructureStatisticsTests(unittest.TestCase):
    def test_metrics_match_enumerated_small_sequences(self):
        for x in itertools.product(range(2), repeat=5):
            pages = [page(list(x), hyphens=[True, False, True, False, False]),
                     page([0, 0, 0, 0, 0])]
            actual = metrics(pages)
            expected = manual_counts(pages)
            np.testing.assert_array_equal(actual[0], expected[0])
            np.testing.assert_allclose(actual[1], expected[1], atol=1e-12)
            self.assertEqual(actual[2], expected[2])

    def test_hard_groups_block_pairs_windows_and_ineligible_boundaries(self):
        pages = [page([1] * 8, groups=[0] * 4 + [1] * 4, segments=[[0, 4], [4, 8]],
                      hyphens=[True] * 8, eligible=[False] * 8),
                 page([1] * 5)]
        a, b, c = metrics(pages)
        self.assertEqual(a[:5].tolist(), [6, 4, 2, 0, 0])
        self.assertEqual(b.tolist(), [0, 0])
        self.assertEqual(c, 4)  # two windows times two, on different pages only

    def test_duplicate_occurrence_multiplicity_and_relabel_scope(self):
        pages = [page([0] * 6), page([0] * 5), page([0] * 4)]
        a, b, c = metrics(pages)
        self.assertEqual(c, 3 * 2 + 3 * 1 + 2 * 1)
        global_relabel = [[(value + 7) % 29 for value in p["indices"]] for p in pages]
        for expected, actual in zip((a, b, c), metrics(pages, global_relabel)):
            np.testing.assert_array_equal(expected, actual)
        independent_relabel = [[i + 1] * len(p["indices"]) for i, p in enumerate(pages)]
        a2, b2, c2 = metrics(pages, independent_relabel)
        np.testing.assert_array_equal(a, a2)
        np.testing.assert_array_equal(b, b2)
        self.assertEqual(c2, 0)  # C is not invariant to separate page alphabets

    def test_symmetric_standardization_max_t_plus_one_and_replay(self):
        pages = [page([0, 0, 1, 2, 1, 0], hyphens=[True, False] * 3)]
        first = randomized_scan(pages, permutations=19, seed=24)
        replay = randomized_scan(pages, permutations=19, seed=24)
        self.assertEqual(first["status"], "completed")
        for name in ("A", "B"):
            family = first["families"][name]
            np.testing.assert_array_equal(family["null"], replay["families"][name]["null"])
            rows = np.vstack((family["observed"], family["null"]))
            np.testing.assert_allclose(family["mean"], rows.mean(axis=0))
            np.testing.assert_allclose(family["std"], rows.std(axis=0), atol=1e-12)
            informative = family["discriminating"]
            maxima = (family["null_z"][:, informative].max(axis=1) if informative.any()
                      else np.zeros(19))
            np.testing.assert_array_equal(family["control_max_z"], maxima)
            for j, z in enumerate(family["observed_z"]):
                expected = (1 + np.count_nonzero(maxima >= z - 1e-12)) / 20 if informative[j] else 1
                self.assertEqual(family["p_adjusted"][j], expected)

    def test_shared_a_c_permutations_belongs_to_enumerated_joint_support(self):
        pages = [page([0, 0, 0, 0, 1]), page([0] * 4)]
        possible = set()
        for shuffled in set(itertools.permutations(pages[0]["indices"])):
            a, _, c = metrics(pages, [list(shuffled), pages[1]["indices"]])
            possible.add((tuple(a), c))
        result = randomized_scan(pages, permutations=19, seed=24)
        for a, c in zip(result["families"]["A"]["null"], result["families"]["C"]["null"]):
            self.assertIn((tuple(a), c), possible)

    def test_rotation_null_is_in_product_of_segment_rotations(self):
        values = [0, 1, 1, 1, 2, 2, 3]
        segments = [[0, 3], [3, 7]]
        pages = [page(values, groups=[0] * 3 + [1] * 4, segments=segments,
                      hyphens=[True, False, False, True, False, False, False])]
        possible = set()
        for first in range(3):
            for second in range(4):
                candidate = (np.roll(values[:3], first).tolist() +
                             np.roll(values[3:], second).tolist())
                possible.add(round(float(metrics(pages, [candidate])[1][0]), 12))
        result = randomized_scan(pages, permutations=39, seed=24)
        for value in result["families"]["B"]["null"][:, 0]:
            self.assertIn(round(float(value), 12), possible)

    def test_constants_are_nondiscriminating(self):
        pages = [page([4] * 6, groups=[0] * 3 + [1] * 3,
                      segments=[[0, 3], [3, 6]], hyphens=[True, False, False] * 2)]
        result = randomized_scan(pages, permutations=19)
        for name in ("A", "B"):
            family = result["families"][name]
            self.assertFalse(family["discriminating"].any())
            self.assertTrue((family["p_adjusted"] == 1).all())
            self.assertFalse(family["lead"].any())
        self.assertFalse(result["families"]["C"]["lead"])

    def test_synthetic_positive_controls(self):
        # A fixed period creates a lag peak without any language or answer key.
        periodic = [page(list(range(17)) * 24)]
        scan_a = randomized_scan(periodic, permutations=299, seed=21)
        self.assertTrue(scan_a["families"]["A"]["lead"][16])
        # Independently rotated segments break the deliberately planted boundary.
        count, width = 35, 8
        boundary = [page(([0] + [1] * (width - 1)) * count,
                         groups=[j for j in range(count) for _ in range(width)],
                         segments=[[j * width, (j + 1) * width] for j in range(count)],
                         hyphens=([True] + [False] * (width - 1)) * count)]
        scan_b = randomized_scan(boundary, permutations=299, seed=22)
        self.assertTrue(scan_b["families"]["B"]["lead"][0])
        # Repeated cross-page strings exceed composition-preserving permutations.
        repeated = [page(list(range(17)) * 6), page(list(range(17)) * 6)]
        scan_c = randomized_scan(repeated, permutations=299, seed=23)
        self.assertTrue(scan_c["families"]["C"]["lead"])
        self.assertLessEqual(scan_c["families"]["C"]["p_adjusted"], FAMILY_ALPHA)

    def test_timeout_retains_completed_controls_but_disables_leads(self):
        pages = [page([0, 1, 0, 1, 0])]
        with patch("lp_lab.structure_stats.time.monotonic", side_effect=[0, 0, 2, 2]):
            result = randomized_scan(pages, permutations=19, timeout_seconds=1)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["completed_control_replicates"], 1)
        self.assertEqual(result["families"]["A"]["null"].shape, (1, 29))
        self.assertFalse(result["families"]["A"]["lead"].any())
        self.assertFalse(result["families"]["B"]["lead"].any())
        self.assertFalse(result["families"]["C"]["lead"])

    def test_invalid_layout_rejected(self):
        invalid = page([0, 1, 0], groups=[0, 1, 0])
        with self.assertRaisesRegex(ValueError, "recur"):
            metrics([invalid])
        with self.assertRaisesRegex(ValueError, "0..28"):
            metrics([page([29])])
        with self.assertRaisesRegex(ValueError, "cross"):
            metrics([page([0, 1], groups=[0, 1])])


if __name__ == "__main__":
    unittest.main()
