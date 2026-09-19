"""Guard the holdout leak and result attribution that earlier gates missed."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import attempt22_pgl_screen_v4 as screen
from attempt22_pgl_screen_v4_worker import select

class PGLScreenV4Tests(unittest.TestCase):
    def test_every_synthetic_holdout_is_disjoint_from_discovery(self):
        reps=screen.legacy.independent_matrices()
        jobs,answers=screen.make_gate(reps,{})
        self.assertEqual(len(jobs),119)
        for job in jobs:
            pages=answers["private"][job["id"]]["pages"]
            self.assertEqual(set(job),{"id","pages"})
            for p in job["pages"]:
                self.assertEqual(set(p),{"page","counts"})
            d_positions={i for p in pages[:2] for i in range(p["start"],p["start"]+p["length"])}
            h=pages[2]
            self.assertTrue(d_positions.isdisjoint(range(h["start"],h["start"]+h["length"])))

    def test_tolerance_tie_is_lexicographic_not_enumeration_order(self):
        import numpy as np
        index,ties=select(np.array([1.,1.+5e-13,0.]),[(2,0,0,1),(1,0,0,1),(3,0,0,1)])
        self.assertEqual((index,ties),(1,2))

if __name__=="__main__":
    unittest.main()
