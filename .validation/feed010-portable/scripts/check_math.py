from pathlib import Path
import argparse
import datetime as dt
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from lp_lab.math_audit import audit
from lp_lab.provenance import verify_sources,code_snapshot,sha256

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    verify_sources(ROOT)
    result=audit(ROOT)
    result.update(started_at_utc=started,finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  hypothesis=json.loads((ROOT/"hypotheses/H005-math-representations-v1.json").read_text(encoding="utf8")),
                  code_version=code_snapshot(ROOT),command=[sys.executable,"-X","utf8","scripts/check_math.py",*sys.argv[1:]],
                  data_versions={p:sha256(ROOT/p) for p in ("data/pages/lp2_56.json","sources/feed002-manifest.json",
                                  "sources/clues-v1/ibot/liber_primus/markdown/05.md")},random_seed=None,exit_code=0)
    (args.out/"audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    summary=dict(status=result["status"],field_pairs=841,centrosymmetric=result["matrix"]["symmetries"]["rotate180"]["equal"],
                 equal_symmetries=[k for k,v in result["matrix"]["symmetries"].items() if v["equal"]],
                 gp_mod29_unique_values=result["gp_mapping"]["mod29_unique_count"],position_stream_primes=result["lp2_position_stream"]["stream_primes_checked"],
                 rune_value_alternative_mismatches=len(result["rune_value_alternative"]["mismatches"]),unsolved_page_candidates=0)
    (args.out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf8")
    print(json.dumps(summary))
    return 0

if __name__=="__main__":
    sys.exit(main())
