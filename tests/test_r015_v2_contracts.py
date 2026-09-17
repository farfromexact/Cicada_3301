import unittest

from lp_lab.r015_bm_v2 import views
from lp_lab.r015_dsl_v2 import apply_stateless, enumerate_recipes
from lp_lab.r015_pgl_v2 import INFINITY, image, matrices, segment_points


class R015V2ContractTests(unittest.TestCase):
    def test_dsl_a_is_registered_reverse_complement(self):
        self.assertEqual(apply_stateless([0, 1, 28], "A"), [28, 27, 0])
        programs, metadata = enumerate_recipes()
        self.assertEqual(metadata["raw_count"], 49)
        self.assertEqual(metadata["unique_count"], len(programs))

    def test_b_has_exactly_four_views_and_one_based_prime_origin(self):
        result = views([0, 1, 2, 3])
        self.assertEqual(set(result), {"raw", "difference", "position_prime_residual",
                                       "position_totient_residual"})
        self.assertEqual(result["difference"], [1, 1, 1])
        self.assertEqual(result["position_prime_residual"][0], 27)  # 0-2 mod29
        self.assertEqual(result["position_totient_residual"][0], 28)  # 0-phi(2) mod29

    def test_c_keeps_slash_and_formatting_inside_segment(self):
        segments, counts = segment_points("a / b a-/b;a", "ab")
        self.assertEqual(segments, [[0, 1, 0, INFINITY, 1], [0]])
        self.assertEqual(counts["slash_boundaries"], 2)
        self.assertEqual(counts["formatting_boundaries"], 3)
        self.assertEqual(counts["other_hard_boundaries"], 1)

    def test_c_exhaustive_representative_count_and_pole(self):
        reps = matrices()
        self.assertEqual(len(reps), 24360)
        self.assertEqual(image(25, (2, 3, 1, 4)), INFINITY)
        self.assertEqual(image(INFINITY, (2, 3, 1, 4)), 2)


if __name__ == "__main__":
    unittest.main()
