from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.model import tokenize
from lp_lab.structure_inputs import prepare_page


def page(raw, number=0):
    name = f"test/{number}"
    return {"page": name, "page_number": number, "raw": raw,
            "tokens": tokenize(raw, name, "synthetic.png", {}),
            "raw_sha256": hashlib.sha256(raw.encode("utf8")).hexdigest(),
            "source": "synthetic-only", "source_sha256": "source-hash",
            "image_path": "synthetic.png", "image_sha256": "image-hash",
            "version": "test-v1", "extraction": {"method": "hand-constructed"}}


class StructuralInputTests(unittest.TestCase):
    def test_line_wrap_does_not_invent_word_start(self):
        result = prepare_page(page("\r\nᛏ/\r\nᚢ-/\r\nᚾ/ᚠ"))
        self.assertEqual(result["indices"], [16, 1, 9, 0])
        self.assertEqual(result["groups"], [0, 0, 0, 0])
        self.assertEqual(result["hyphen_mask"], [0, 0, 1, 0])
        self.assertEqual(result["boundary_eligible"], [False, True, True, True])
        self.assertEqual(result["segments"], [[0, 4]])
        reversed_order = prepare_page(page("ᚠ/-ᚢ"))
        self.assertEqual(reversed_order["hyphen_mask"], [0, 1])

    def test_hard_boundaries_never_bridge_rune_fragments(self):
        result = prepare_page(page("&\r\nᚠ-ᚢ;&$§%\"'12A/-ᚦᚩ/&"))
        self.assertEqual(result["indices"], [0, 1, 2, 3])
        self.assertEqual(result["groups"], [0, 0, 1, 1])
        self.assertEqual(result["segments"], [[0, 2], [2, 4]])
        self.assertEqual(result["hyphen_mask"], [0, 1, 0, 0])
        self.assertEqual(result["boundary_eligible"], [False, True, False, True])
        for delimiter in "&$§%;\"'0123456789AZ":
            with self.subTest(delimiter=delimiter):
                split = prepare_page(page("ᚠ-" + delimiter + "-ᚢ"))
                self.assertEqual(split["segments"], [[0, 1], [1, 2]])
                self.assertEqual(split["hyphen_mask"], [0, 0])

    def test_registered_soft_markers_do_not_split_analysis_span(self):
        result = prepare_page(page("ᚠ.ᚢ,ᚦ/ \r\n\tᚩ-ᚱ"))
        self.assertEqual(result["groups"], [0] * 5)
        self.assertEqual(result["hyphen_mask"], [0, 0, 0, 0, 1])

    def test_preserves_raw_mapping_and_provenance(self):
        original = page("\r\nᚠ-/\r\nᛠ;ᚢ")
        before = deepcopy(original)
        result = prepare_page(original)
        self.assertEqual(original, before)
        self.assertEqual(result["indices"], [0, 28, 1])
        for rune_token in result["rune_tokens"]:
            self.assertIs(rune_token, original["tokens"][rune_token["source_offset"]])
            self.assertEqual(original["raw"][rune_token["source_offset"]], rune_token["raw"])
        for key in ("raw_sha256", "source_sha256", "image_sha256", "version", "extraction"):
            self.assertEqual(result["metadata"][key], original[key])

    def test_grid_only_page_is_inapplicable_without_empty_segments(self):
        result = prepare_page(page("\r\n2M-0w-3L/\r\n", 50))
        for key in ("indices", "groups", "hyphen_mask", "boundary_eligible", "rune_tokens", "segments"):
            self.assertEqual(result[key], [])
        self.assertFalse(result["metadata"]["applicability"]["rune_structure"])
        self.assertIn("No GP rune", result["metadata"]["applicability"]["reason"])

    def test_corrupt_raw_or_rune_mapping_fails(self):
        mutations = [
            lambda p: p["tokens"].pop(),
            lambda p: p["tokens"][0].update(source_offset=1),
            lambda p: p["tokens"][0].update(rune_ordinal=1),
            lambda p: p["tokens"][0]["rune"].update(index=29),
            lambda p: p["tokens"][0]["rune"].update(index=2),
            lambda p: p["tokens"][0].update(rune=None),
            lambda p: p["tokens"][0].update(kind="literal"),
            lambda p: p.update(raw_sha256="incorrect"),
            lambda p: p.update(indices=[0, 0]),
            lambda p: p.update(rune_count=99),
        ]
        for mutation in mutations:
            sample = page("ᚠᚢ")
            mutation(sample)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                prepare_page(sample)

    def test_unregistered_runic_literal_is_rejected(self):
        sample = page("ᚠ")
        sample["raw"] = "ᚡ"
        sample.pop("raw_sha256")
        sample["tokens"][0].update(raw="ᚡ", kind="literal", rune=None, rune_ordinal=None)
        with self.assertRaisesRegex(ValueError, "Unregistered rune"):
            prepare_page(sample)


if __name__ == "__main__":
    unittest.main()
