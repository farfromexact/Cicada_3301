from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from lp_lab.research import validate,find,method_entries

class MethodTests(unittest.TestCase):
    def test_preference_retrieval_retains_attribution(self):
        result=find(ROOT,"非暴力")
        method=next(m for m in result["methods"] if m["id"]=="M002")
        self.assertEqual(method["kind"],"user_preference")
        self.assertEqual(next(m for m in method_entries(ROOT) if m["id"]=="M005")["kind"],"assistant_interpretation")

    def test_method_is_not_a_reproduced_cipher_claim(self):
        methods=method_entries(ROOT)
        methods[0]["kind"]="reproduced"
        with patch("lp_lab.research.method_entries",return_value=methods):
            with self.assertRaises(ValueError):
                validate(ROOT)

if __name__=="__main__":
    unittest.main()
