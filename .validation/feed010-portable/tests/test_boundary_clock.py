from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.boundary_clock import BRANCHES, transform


class BoundaryClockTests(unittest.TestCase):
    """Tiny hand-computed cases, deliberately no real-source answer access."""

    def test_continuous_and_fixed_skip_trace(self):
        result = transform("ᚠᚢ-ᚦᚩ", "continuous", skip_ordinal=1)
        # prime-minus-one slots 1, 2, 4; ordinal1 is copied, not consumed.
        self.assertEqual(result["indices"], [28, 1, 0, 28])
        self.assertEqual([s["stream_index"] for s in result["steps"]], [0, None, 1, 2])
        self.assertEqual([s["source_offset"] for s in result["steps"]], [0, 1, 3, 4])
        self.assertEqual(result["steps"][1]["clock_before"], 1)
        self.assertEqual(result["steps"][1]["clock_after"], 1)
        self.assertEqual(result["final_clock"], 3)

    def test_line_and_paragraph_resets_ignore_newlines(self):
        raw = "ᚠᚠ/\nᚠ&ᚠ"
        line = transform(raw, "line_reset", skip_ordinal=None)
        paragraph = transform(raw, "paragraph_reset", skip_ordinal=None)
        self.assertEqual(line["indices"], [28, 27, 28, 27])
        self.assertEqual(paragraph["indices"], [28, 27, 25, 28])
        self.assertEqual(line["events"], [dict(event="reset", reason="line_reset",
                            raw="/", source_offset=2, timing="after", clock_before=2, clock_after=0)])
        self.assertEqual(paragraph["events"][0]["source_offset"], 5)

    def test_title_reset_precedes_registered_codepoint(self):
        result = transform("ᚠ-ᚠᚠ", "title_reset", skip_ordinal=None, title_boundary=2)
        self.assertEqual(result["indices"], [28, 28, 27])
        self.assertEqual(result["events"][0]["timing"], "before")
        self.assertEqual(result["events"][0]["clock_before"], 1)

    def test_hash_advances_only_registered_literal_characters(self):
        result = transform("ᚠab/\nᚠ9", "hash_advance", skip_ordinal=None,
                           hash_spans=((1, 3),))
        # First rune consumes prime2, a/b consume prime3/5, last rune uses prime7.
        self.assertEqual(result["indices"], [28, 23])
        self.assertEqual([e["source_offset"] for e in result["events"]], [1, 2])
        self.assertEqual([e["prime"] for e in result["events"]], [3, 5])
        self.assertEqual(result["final_clock"], 4)
        self.assertTrue(result["raw"].endswith("9"))

    def test_delimiters_include_semicolon_and_exclude_hex_whitespace(self):
        result = transform("ᚠ-;\n a/ᚠ&$", "delimiter_advance", skip_ordinal=None)
        # Rune0 consumes slot0, -, ;, / consume slots1..3, Rune1 uses prime11.
        self.assertEqual(result["indices"], [28, 19])
        self.assertEqual([e["raw"] for e in result["events"]], ["-", ";", "/", "&", "$"])
        self.assertEqual(result["final_clock"], 7)

    def test_raw_inverse_preserves_every_literal_and_skip_position(self):
        raw = "ᚠᚢ./\n&ab-ᚦ;$"
        for branch in BRANCHES:
            with self.subTest(branch=branch):
                parameters = dict(skip_ordinal=1, title_boundary=2, hash_spans=((6, 8),))
                decoded = transform(raw, branch, **parameters)
                encrypted = transform(decoded["raw"], branch, encrypt=True, **parameters)
                self.assertEqual(encrypted["raw"], raw)
                self.assertEqual(decoded["raw"][2:9], raw[2:9])
                self.assertEqual(decoded["steps"][1]["input_index"], 1)
                self.assertEqual(decoded["steps"][1]["output_index"], 1)

    def test_invalid_inputs_fail_without_normalization(self):
        for raw, branch, kwargs in [
            ("ᚡ", "continuous", dict(skip_ordinal=None)),
            ("ᚠ", "unknown", dict(skip_ordinal=None)),
            ("ᚠ", "continuous", dict(skip_ordinal=1)),
            ("ᚠ", "title_reset", dict(skip_ordinal=None, title_boundary=1)),
            ("ᚠa/", "hash_advance", dict(skip_ordinal=None, hash_spans=((1, 3),))),
            ("ᚠab", "hash_advance", dict(skip_ordinal=None, hash_spans=((2, 3), (1, 2)))),
        ]:
            with self.subTest(raw=raw, branch=branch, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    transform(raw, branch, **kwargs)


if __name__ == "__main__":
    unittest.main()
