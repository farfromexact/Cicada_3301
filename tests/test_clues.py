from pathlib import Path
import copy
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "src"))
from lp_lab.clues import warning_check,matrix_check
from lp_lab.research import read_knowledge,validate,find

class ClueTests(unittest.TestCase):
    def test_warning_from_original_and_identity_negative(self):
        result=warning_check(ROOT)
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["rune_count"],184)
        self.assertEqual(len(result["negative_control"]["mismatches"]),182)

    def test_matrix_cells_and_structure(self):
        result=matrix_check(ROOT)
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["row_sums"]+result["column_sums"]+result["diagonals"],[1033]*12)

    def test_graph_provenance_and_prior_negative(self):
        self.assertEqual(validate(ROOT)["claims"],9)
        found=find(ROOT,"no-skip")
        self.assertTrue(any(e["outcome"]=="negative" for e in found["experiments"]))

    def test_cannot_promote_untested_interpretation(self):
        doc=copy.deepcopy(read_knowledge(ROOT))
        next(c for c in doc["claims"] if c["id"]=="C007")["status"]="reproduced"
        with self.assertRaises(ValueError):
            validate(ROOT,doc)

    def test_rejects_missing_source_locator(self):
        doc=copy.deepcopy(read_knowledge(ROOT))
        doc["claims"][0]["evidence"][0]["anchor"]="nonexistent literal locator"
        with self.assertRaises(ValueError):
            validate(ROOT,doc)

if __name__=="__main__":
    unittest.main()
