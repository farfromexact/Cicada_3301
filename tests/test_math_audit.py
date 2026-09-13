from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from lp_lab.math_audit import phi,symmetry_checks,audit

class MathAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=audit(ROOT)

    def test_phi_composite_and_boundary_values(self):
        self.assertEqual([phi(n) for n in (1,2,9,12,29)],[1,1,6,4,28])
        with self.assertRaises(ValueError):
            phi(0)

    def test_finite_field_and_no_zero_inverse(self):
        rows=self.result["field"]["inverses"]
        self.assertEqual(rows[0]["inverses"],[])
        self.assertEqual(rows[2]["inverses"],[15])
        self.assertTrue(all(len(r["inverses"])==1 for r in rows[1:]))

    def test_asymmetric_control_and_invalid_shape(self):
        r=symmetry_checks([[1,2,3],[4,5,6],[7,8,9]])
        self.assertEqual([k for k,v in r.items() if v["equal"]],["identity"])
        with self.assertRaises(ValueError):
            symmetry_checks([[1,2]])

    def test_mapping_collision_is_not_reversible(self):
        r=self.result["gp_mapping"]
        self.assertEqual(r["full_prime_unique_count"],29)
        self.assertEqual(r["mod29_unique_count"],24)
        self.assertGreater(len(r["mod29_collisions"]["2"]),1)

    def test_position_and_rune_value_controls_differ(self):
        self.assertEqual(self.result["lp2_position_stream"]["status"],"passed")
        self.assertEqual(len(self.result["rune_value_alternative"]["mismatches"]),80)

if __name__=="__main__":
    unittest.main()
