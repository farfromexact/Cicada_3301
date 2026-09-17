"""Guarded H016-v3 worker; stdin contains public ciphertext jobs only."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt13_worker_v2 as base


base.HYPOTHESIS = "H016-periodic-plaintext-F-state-v3"


if __name__ == "__main__":
    base.main()
