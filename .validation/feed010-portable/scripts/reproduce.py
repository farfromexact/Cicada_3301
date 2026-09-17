from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.cipher import transform
from lp_lab.model import tokenize
from lp_lab.runes import indices
from lp_lab.reference import reference_indices

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    reports = []
    for page in (56, 57):
        record = json.loads((ROOT / f"data/pages/lp2_{page}.json").read_text(encoding="utf8"))
        params = record["parameters"]
        decoded = transform(record["tokens"], **params)
        expected = reference_indices(ROOT / record["cross_source"]["path"])
        actual = indices(decoded["raw"])
        plain_tokens = tokenize(decoded["raw"], record["page"], record["image_path"], record["regions"])
        encrypted = transform(plain_tokens, **params, encrypt=True)
        exact = actual == expected
        roundtrip = encrypted["raw"] == record["raw"]
        positions = [dict(ordinal=i, expected=e, actual=a, equal=e == a)
                     for i, (e, a) in enumerate(zip(expected, actual))]
        negative = None
        if page == 56:
            unskipped = transform(record["tokens"], **{**params, "skip": []})
            mismatch = [i for i,(a,b) in enumerate(zip(indices(unskipped["raw"]), expected)) if a != b]
            negative = dict(parameters={**params, "skip": []}, mismatch_ordinals=mismatch,
                            raw=unskipped["raw"], latin=unskipped["latin"], status="negative")
        artifact = dict(parameters=params, decoded=decoded, expected_indices=expected,
                        comparison=positions, exact_runes=exact, roundtrip_exact=roundtrip,
                        reencrypted_raw=encrypted["raw"], negative_control=negative)
        (args.out / f"lp2_{page}.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
        (args.out / f"lp2_{page}.txt").write_text(decoded["latin"], encoding="utf8")
        reports.append(dict(page=page, rune_count=len(actual), exact_runes=exact,
                            roundtrip_exact=roundtrip, primes_consumed=decoded["primes_consumed"],
                            negative_mismatches=len(negative["mismatch_ordinals"]) if negative else None))
    print(json.dumps(reports))
    return 0 if all(r["exact_runes"] and r["roundtrip_exact"] for r in reports) else 1

if __name__ == "__main__":
    sys.exit(main())
