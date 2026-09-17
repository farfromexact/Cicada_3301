from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import attempt10_circumference_transfer as circumference


class CircumferenceTransferTests(unittest.TestCase):
    def test_source_gate_is_exact(self):
        gate = circumference.load_source_gate()
        result = circumference.known_gate(gate)
        self.assertEqual(result["input_runes"], 226)
        self.assertEqual(result["mismatch_count"], 0)
        self.assertTrue(result["inverse_roundtrip"])

    def test_key_roundtrip_both_f_policies(self):
        values = [0, 1, 2, 0, 28, 4]
        for consume_zero in (False, True):
            plain, terminal = circumference.decrypt(values, 3, consume_zero)
            skips = tuple(i for i, value in enumerate(values) if value == 0) if not consume_zero else ()
            cipher, inverse_terminal = circumference.encrypt(plain, 3, consume_zero, skips)
            self.assertEqual(cipher, values)
            self.assertEqual(inverse_terminal, terminal)

    def test_branch_decoder_and_independent_path_agree(self):
        pages = [dict(page="LP2/test", indices=[0, 1, 2, 0], raw="", raw_sha256="",
                      page_number=0, source="", image_path="")]
        rows = circumference.decode_pages(pages, [0.0] * 29)
        checked = circumference.validate_rows(pages, rows, [0.0] * 29)
        self.assertEqual(checked["status"], "passed")
        self.assertEqual(checked["rune_checks"], 16)

    def test_corpus_applicability_is_pinned(self):
        pages = circumference.load_pages()
        self.assertEqual(len(pages), 56)
        self.assertEqual([p["page"] for p in pages if not p["indices"]], ["LP2/50"])
        self.assertEqual(sum(p["rune_count"] for p in pages), 12956)


if __name__ == "__main__":
    unittest.main()
