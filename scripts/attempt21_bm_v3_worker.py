"""Guarded H030-v3 worker; only public ciphertext jobs are accepted."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt21_bm_v2_worker as base


base.HYPOTHESIS = "H030-berlekamp-massey-v3"


if __name__ == "__main__":
    base.main()
