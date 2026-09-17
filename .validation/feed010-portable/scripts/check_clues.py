from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "src"))
from lp_lab.clues import warning_check,matrix_check
from lp_lab.provenance import verify_sources

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    verify_sources(ROOT)
    warning,matrix = warning_check(ROOT),matrix_check(ROOT)
    for name, obj in (("warning",warning),("matrix",matrix)):
        (args.out / f"{name}.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    summary = dict(warning_status=warning["status"],warning_runes=warning["rune_count"],
        warning_identity_mismatches=len(warning["negative_control"]["mismatches"]),matrix_status=matrix["status"],matrix_cells=25,
        row_sums=matrix["row_sums"],column_sums=matrix["column_sums"],diagonals=matrix["diagonals"],unsolved_candidates=0)
    summary["status"] = "passed" if warning["status"]==matrix["status"]=="passed" else "negative"
    (args.out / "summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf8")
    print(json.dumps(summary))
    return 0  # Completed comparisons, including negative ones, are not program errors.

if __name__ == "__main__":
    sys.exit(main())
