"""Guarded H030-v4 observed/gate worker; arithmetic inherited unchanged."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt21_bm_v2_worker as base

base.HYPOTHESIS = "H030-berlekamp-massey-v4"

if __name__ == "__main__":
    base.main()
