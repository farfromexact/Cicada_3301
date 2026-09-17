"""H018-v2 worker wrapper with a separately frozen hypothesis identifier."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt15_projection_worker_v1 as base_worker


base_worker.HYPOTHESIS = "H018-fourth-power-projection-v2"


def __getattr__(name):
    return getattr(base_worker, name)


if __name__ == "__main__":
    base_worker.main()
