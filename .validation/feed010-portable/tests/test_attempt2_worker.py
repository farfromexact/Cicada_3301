from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]


class KnownWorkerIsolationTests(unittest.TestCase):
    def public(self):
        return dict(schema=1,experiment="attempt2-mechanics-v1",jobs=[dict(
            id="toy",kind="skip",pages=[dict(page="toy",raw="ᚢ-ᚠ/ᚦ")],
            parameters=dict(mode="vigenere",direction="subtract",policy="specified_free",
                            continuity="continuous",specified_skip=[1],key=[1,2]))])

    def invoke(self,public):
        return subprocess.run([sys.executable,"-I","-S",str(ROOT/"scripts/attempt2_worker.py")],
                              input=json.dumps(public),capture_output=True,text=True,encoding="utf8",timeout=10)

    def test_guard_and_exact_toy(self):
        proc=self.invoke(self.public())
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(proc.stdout)
        self.assertTrue(result["read_guard_probe_passed"])
        self.assertEqual(result["results"][0]["result"]["pages"][0]["raw"],"ᚠ-ᚠ/ᚠ")

    def test_reference_and_seed_fields_rejected(self):
        for field in ("expected","seed"):
            public=self.public()
            public[field]=[1,2,3]
            result=self.invoke(public)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("Unexpected public fields",result.stderr)


if __name__=="__main__":
    unittest.main()
