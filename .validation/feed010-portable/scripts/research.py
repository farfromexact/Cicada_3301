from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "src"))
from lp_lab.research import validate,find
from lp_lab.provenance import verify_sources

parser = argparse.ArgumentParser()
parser.add_argument("command",choices=["find","validate"])
parser.add_argument("query",nargs="?")
args = parser.parse_args()
verify_sources(ROOT)
result = validate(ROOT)
if args.command == "find":
    if not args.query:
        parser.error("find requires a query")
    result = find(ROOT,args.query)
print(json.dumps(result,ensure_ascii=False,indent=2))
