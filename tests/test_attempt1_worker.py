from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("attempt1_worker", ROOT/"scripts/attempt1_worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class FixedClockWorkerTests(unittest.TestCase):
    def public(self):
        return dict(schema=1,hypothesis="H006-v1",training_counts=[1]*29,
                    pages=[dict(page=f"test/{i}",cipher=[0]*5,line_starts=[0,2],paragraph_starts=[0,3]) for i in range(2)])

    def test_manual_prime_clock_and_aliases(self):
        result = worker.run(self.public())
        rows = {(r["page"],m):r for r in result["results"] for m in r["methods"]}
        self.assertEqual(rows[("test/0","page")]["delta"],[1,2,4,6,10])
        self.assertEqual(rows[("test/0","line")]["delta"],[1,2,1,2,4])
        self.assertEqual(rows[("test/0","paragraph")]["delta"],[1,2,4,1,2])
        self.assertEqual(rows[("test/1","corpus")]["delta"],[12,16,18,22,28])
        self.assertEqual(rows[("test/0","page")]["methods"],["page","corpus"])
        self.assertEqual(result["unique_evaluations"],7)

    def test_guard_and_rejected_secret_field(self):
        command = [sys.executable,"-I","-S",str(ROOT/"scripts/attempt1_worker.py")]
        public = self.public()
        good = subprocess.run(command,input=json.dumps(public),capture_output=True,text=True,encoding="utf8",timeout=10)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertTrue(json.loads(good.stdout)["read_guard_probe_passed"])
        public["seed"] = 123
        bad = subprocess.run(command,input=json.dumps(public),capture_output=True,text=True,encoding="utf8",timeout=10)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn("Unexpected public fields",bad.stderr)

    def test_bad_boundaries_fail(self):
        public = self.public()
        public["pages"][0]["line_starts"] = [0,5]
        with self.assertRaises(ValueError):
            worker.run(public)


if __name__ == "__main__":
    unittest.main()
