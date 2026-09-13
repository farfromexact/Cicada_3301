from pathlib import Path
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.runes import RUNES, GP, LATIN, indices, rune
from lp_lab.model import tokenize
from lp_lab.cipher import transform
from lp_lab.reference import reference_indices, segment_word
from lp_lab.provenance import verify_sources
from lp_lab.synthetic import generate, verify
from lp_lab.execution import execute

def load(page):
    return json.loads((ROOT / f"data/pages/lp2_{page}.json").read_text(encoding="utf8"))

class DataTests(unittest.TestCase):
    def test_pinned_source_hashes(self):
        self.assertEqual(verify_sources(ROOT), 29)

    def test_mapping_against_pinned_gp_table(self):
        rows = (ROOT / "sources/ibot/other/Gematria_Primus.md").read_text(encoding="utf8").splitlines()
        rows = [line for line in rows if line.startswith("| ") and any(c in RUNES for c in line)]
        self.assertEqual(len(rows), 29)
        for row in rows:
            glyph, latin, prime, index, _, _ = [s.strip() for s in row.strip("|").split("|")]
            r = rune(glyph)
            self.assertEqual((r.index, r.prime_value, r.latin_options), (int(index), int(prime), tuple(latin.split("/"))))

    def test_lossless_tokens_and_locations(self):
        for page in (56,57):
            record = load(page)
            self.assertEqual("".join(t["raw"] for t in record["tokens"]), record["raw"])
            runes = [t for t in record["tokens"] if t["kind"] == "rune"]
            self.assertEqual([t["rune_ordinal"] for t in runes], list(range(len(runes))))
            for t in runes:
                self.assertIsNotNone(t["image"]["bbox"])
                self.assertEqual(t["raw"], record["raw"][t["source_offset"]])

    def test_transcription_is_exact_master_slice(self):
        for page in (56,57):
            record = load(page)
            master = (ROOT / record["source"]).read_text(encoding="utf8")
            self.assertEqual(record["raw"], master.split("%")[record["extraction"]["segment_index"]])

    def test_unknown_rune_is_error(self):
        with self.assertRaises(ValueError):
            tokenize("ᚡ", "test", "image", {})

    def test_delimiter_ambiguity_is_preserved(self):
        t = next(t for t in load(56)["tokens"] if t["raw"] == ";")
        self.assertEqual(t["ambiguity"][0]["status"], "unresolved")

class RegressionTests(unittest.TestCase):
    def test_exact_rune_references_and_inverse(self):
        for page in (56,57):
            rec = load(page)
            decoded = transform(rec["tokens"], **rec["parameters"])
            self.assertEqual(indices(decoded["raw"]), reference_indices(ROOT / rec["cross_source"]["path"]))
            plain = tokenize(decoded["raw"], rec["page"], rec["image_path"], rec["regions"])
            self.assertEqual(transform(plain, **rec["parameters"], encrypt=True)["raw"], rec["raw"])

    def test_no_skip_negative_and_first_divergence(self):
        rec = load(56)
        bad = indices(transform(rec["tokens"], **{**rec["parameters"], "skip":[]})["raw"])
        expected = reference_indices(ROOT / rec["cross_source"]["path"])
        failures = [i for i,(a,b) in enumerate(zip(bad,expected)) if a != b]
        self.assertEqual(failures[0],56)
        self.assertEqual(len(failures),29)

    def test_input_mutation_cannot_pass(self):
        rec = load(56)
        mutated = copy.deepcopy(rec["tokens"])
        first = next(t for t in mutated if t["kind"] == "rune")
        first["rune"]["index"] = (first["rune"]["index"]+1)%29
        decoded = indices(transform(mutated, **rec["parameters"])["raw"])
        self.assertNotEqual(decoded, reference_indices(ROOT / rec["cross_source"]["path"]))

    def test_wrong_prime_offset_cannot_pass(self):
        rec = load(56)
        actual = indices(transform(rec["tokens"], **{**rec["parameters"], "offset":1})["raw"])
        self.assertNotEqual(actual, reference_indices(ROOT / rec["cross_source"]["path"]))

    def test_identity_57(self):
        rec = load(57)
        self.assertEqual(transform(rec["tokens"], **rec["parameters"])["raw"], rec["raw"])

    def test_invalid_skip_rejected(self):
        with self.assertRaises(ValueError):
            transform(load(56)["tokens"], skip=[202])

    def test_reference_segmentation_not_greedy(self):
        self.assertEqual(segment_word("THE",2),[2,18])
        self.assertEqual(segment_word("THE",3),[16,8,18])
        with self.assertRaises(ValueError):
            segment_word("THE",1)

class ProtocolTests(unittest.TestCase):
    def test_verifier_requires_full_answer_not_just_roundtrip(self):
        cipher, answer = generate([0,1,2,3,4], 417)
        good = dict(selected=answer["key"], plaintext=answer["plaintext"])
        self.assertEqual(verify(answer,good,cipher)["status"],"passed")
        bad = copy.deepcopy(good)
        bad["selected"]["shift"] = (bad["selected"]["shift"]+1)%29
        bad["plaintext"] = [(p+1)%29 for p in bad["plaintext"]]
        result = verify(answer,bad,cipher)
        self.assertTrue(result["roundtrip"])
        self.assertEqual(result["status"],"negative")

    def test_worker_rejects_seed_field(self):
        result = execute([sys.executable,"-I","-S",str(ROOT / "scripts/search_worker.py")],
                         cwd=ROOT, timeout=5, stdin=json.dumps(dict(seed=123)))
        self.assertEqual(result["status"],"error")
        self.assertIn("Unexpected public fields",result["stderr"])

    def test_nonzero_is_error(self):
        result = execute([sys.executable,"-c","raise RuntimeError('control')"],cwd=ROOT,timeout=5)
        self.assertEqual(result["status"],"error")
        self.assertNotEqual(result["exit_code"],0)

    def test_timeout_is_separate(self):
        with patch("lp_lab.execution.subprocess.run",side_effect=subprocess.TimeoutExpired(["test"],1)):
            result = execute(["test"],cwd=ROOT,timeout=1)
        self.assertEqual(result["status"],"timeout")
        self.assertIsNone(result["exit_code"])

    def test_real_timeout(self):
        result = execute([sys.executable,"-c","import time; time.sleep(2)"],cwd=ROOT,timeout=0.1)
        self.assertEqual(result["status"],"timeout")
        self.assertIsNone(result["exit_code"])

if __name__ == "__main__":
    unittest.main()
