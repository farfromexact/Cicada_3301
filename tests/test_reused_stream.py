import copy
import importlib.util
import itertools
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


worker = module("h027_worker", "attempt23_reused_stream_worker_v1.py")
runner = module("h027_runner", "attempt23_reused_stream_v1.py")


class ReusedStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.u = [i % 7 + 1 for i in range(29)]
        cls.b = [[(a * 13 + b * 7) % 31 for b in range(29)] for a in range(29)]
        cls.wm = worker.model_from_counts(cls.u, cls.b)
        cls.vm = runner.verifier_model(cls.u, cls.b)

    def test_independent_difference_convolution(self):
        for a in range(29):
            self.assertAlmostEqual(math.exp(self.wm["log_dpi"][a]), self.vm["dpi"][a], places=12)
            for b in range(29):
                self.assertAlmostEqual(math.exp(self.wm["log_dt"][a][b]), self.vm["dt"][a][b], places=12)

    def test_short_exhaustive_oracle(self):
        d = [3, 0, 28]
        for previous in (None, (4, 9)):
            a, b, optimum = worker.viterbi(d, self.wm, previous)
            brute = max(runner.path_objective(list(candidate), [(x - y) % 29 for x, y in zip(candidate, d)], self.vm, previous) for candidate in itertools.product(range(29), repeat=3))
            self.assertAlmostEqual(optimum, brute, places=10)
            self.assertAlmostEqual(runner.backward_optimum(d, self.vm, previous), brute, places=10)
            self.assertAlmostEqual(runner.path_objective(a, b, self.vm, previous), brute, places=10)

    def test_discovery_does_not_read_suffix(self):
        job = dict(id="opaque", a=[i % 29 for i in range(60)], b=[(i * 7) % 29 for i in range(60)])
        modified = copy.deepcopy(job)
        modified["b"][40:] = [(v + 1) % 29 for v in modified["b"][40:]]
        left, right = worker.run_job(job, self.wm), worker.run_job(modified, self.wm)
        self.assertEqual(left["a"][:40], right["a"][:40])
        self.assertEqual(left["b"][:40], right["b"][:40])
        self.assertEqual(left["viterbi_scores"][0], right["viterbi_scores"][0])

    def test_output_mutations_rejected(self):
        job = dict(id="opaque", a=[i % 29 for i in range(30)], b=[i * 3 % 29 for i in range(30)])
        public = dict(schema=1, hypothesis=worker.HYPOTHESIS, unigram_counts=self.u, bigram_counts=self.b, jobs=[job])
        output = dict(status="completed", read_guard_probe_passed=True, jobs=[worker.run_job(job, self.wm)])
        self.assertEqual(runner.verify_output(public, output, self.vm)["status"], "passed")
        for field in ("a", "key_a", "difference", "log_bf", "viterbi_scores"):
            bad = copy.deepcopy(output)
            bad["jobs"][0][field][0] += 1
            with self.assertRaises(ValueError):
                runner.verify_output(public, bad, self.vm)

    def test_private_fields_rejected(self):
        public = dict(schema=1, hypothesis=worker.HYPOTHESIS, unigram_counts=self.u, bigram_counts=self.b, jobs=[dict(id="x", a=[0] * 30, b=[0] * 30)])
        worker.validate_public(public)
        for name in ("seed", "answers", "plaintext", "key"):
            bad = copy.deepcopy(public)
            bad[name] = 0
            with self.assertRaises(ValueError):
                worker.validate_public(bad)


if __name__ == "__main__":
    unittest.main()
