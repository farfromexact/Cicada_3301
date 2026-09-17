from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from lp_lab.geometry_audit import ring_paths, traversals, inspect_grid, audit

class GeometryAuditTests(unittest.TestCase):
    def test_feed_matrix_final_row_without_latex_line_terminator(self):
        result=audit(ROOT)
        self.assertEqual(result['status'],'passed')
        self.assertTrue(result['feed_numeric_matrix_matches_pinned_transcription'])
        self.assertEqual(result['coverage']['unsolved_page_candidates'],0)

    def test_hand_labelled_spiral_and_inverse(self):
        self.assertEqual(ring_paths(3), [[(0,0),(0,1),(0,2),(1,2),(2,2),(2,1),(2,0),(1,0)],[(1,1)]])
        paths=traversals(3)
        self.assertEqual(paths['transpose0-rotate0-inward'][-1],(1,1))
        self.assertEqual(paths['transpose0-rotate0-outward'][0],(1,1))
        self.assertEqual(len({tuple(p) for p in paths.values()}),16)
        result=inspect_grid([[1,2,3],[4,5,6],[7,8,9]])
        self.assertTrue(result['exact_properties_passed'])
        self.assertEqual(result['unique_sequences']['integer_cell'],16)

    def test_uniform_grid_deduplicates_all_paths(self):
        result=inspect_grid([[2]*5 for _ in range(5)])
        self.assertEqual(result['unique_sequences'],dict(integer_cell=1,cell_mod29=1,phi_cell_mod29=1))
        self.assertTrue(result['exact_properties_passed'])

    def test_reject_invalid_geometry(self):
        for n in (0,2,-1,True):
            with self.assertRaises(ValueError): ring_paths(n)
        with self.assertRaises(ValueError): inspect_grid([[1,2],[3]])
