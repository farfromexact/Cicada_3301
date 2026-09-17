"""Run the corrected H018-v2 power-gated LP2 diagnostic."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt15_projection_v1 as base_runner


base_runner.HYPOTHESIS = "H018-fourth-power-projection-v2"
base_runner.SPEC_PATH = ROOT / "hypotheses/H018-fourth-power-projection-v2.json"
base_runner.WORKER_PATH = ROOT / "scripts/attempt15_projection_worker_v2.py"


def __getattr__(name):
    return getattr(base_runner, name)


if __name__ == "__main__":
    base_runner.main()
