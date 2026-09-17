"""Run H012: source-directed LP1/06 reverse-plus-three regression."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import platform
import random
import re
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.reference import reference_indices
from lp_lab.runes import RUNES, indices

SPEC_PATH = ROOT / "hypotheses/H012-koan-reverse-shift-v1.json"
SOURCE_PATH = ROOT / "sources/clues-v1/ibot/liber_primus/markdown/06.md"
CONTROL_SEED = 33011201
CONTROL_COUNT = 32
REGISTERED_A = 28
REGISTERED_B = 2


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf8")


def stable_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def fenced_blocks(text):
    return re.findall(r"```[^\r\n]*\r?\n(.*?)```", text, re.S)


def load_reference():
    source = SOURCE_PATH.read_text(encoding="utf8")
    blocks = fenced_blocks(source)
    if len(blocks) < 2:
        raise ValueError("LP1/06 source does not contain the registered one-line block")
    cipher = indices(blocks[1])
    expected = reference_indices(SOURCE_PATH)
    if len(cipher) != len(expected) or len(cipher) != 209:
        raise ValueError("LP1/06 reference length changed")
    return source, blocks[1], cipher, expected


def affine(values, a, b):
    if not (1 <= a < 29 and 0 <= b < 29 and math.gcd(a, 29) == 1):
        raise ValueError("Affine coefficients must be invertible in Z/29Z")
    return [(a * value + b) % 29 for value in values]


def control_pairs():
    rng = random.Random(CONTROL_SEED)
    pairs = []
    while len(pairs) < CONTROL_COUNT:
        pair = (rng.randrange(1, 29), rng.randrange(29))
        if pair != (REGISTERED_A, REGISTERED_B) and pair not in pairs:
            pairs.append(pair)
    return pairs


def archive_run(run, snapshot):
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / path for path in snapshot["files"]]
    paths.extend(path for directory in ("data", "sources", "hypotheses", "research")
                 for path in (ROOT / directory).rglob("*") if path.is_file())
    paths.extend(path for path in run.rglob("*") if path.is_file() and path != archive)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive),
                bytes=archive.stat().st_size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Run folder must be inside repository runs")
    run.mkdir(parents=True, exist_ok=False)
    started = dt.datetime.now(dt.timezone.utc)
    wall_started = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis="H012-koan-reverse-shift-v1",
                  attempt="auto-cycle R004 method-family-switch", status="running",
                  started_at_utc=started.isoformat(), python=sys.version,
                  executable=sys.executable, platform=platform.platform(),
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        source, raw_cipher, cipher, expected = load_reference()
        pairs = control_pairs()
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH),
                      source_sha256=sha256(SOURCE_PATH), source_files_verified=source_count,
                      code_version=snapshot, source_block="one-line block index 1",
                      cipher_length=len(cipher), reference_length=len(expected),
                      cipher_sha256=stable_digest(cipher), expected_sha256=stable_digest(expected),
                      registered_affine=dict(a=REGISTERED_A, b=REGISTERED_B),
                      random_control_pairs=[dict(a=a, b=b) for a, b in pairs],
                      control_seed=CONTROL_SEED, control_count=CONTROL_COUNT,
                      success_criterion=spec["scorer_and_acceptance_version"]["success"])
        write_json(run / "frozen.json", frozen)
        record.update(frozen_sha256=sha256(run / "frozen.json"), source_files_verified=source_count)
        write_json(run / "record.json", record)

        decoded = affine(cipher, REGISTERED_A, REGISTERED_B)
        mismatches = [i for i, (actual, target) in enumerate(zip(decoded, expected)) if actual != target]
        inverse = affine(decoded, REGISTERED_A, REGISTERED_B)
        observed = dict(a=REGISTERED_A, b=REGISTERED_B, input_runes=len(cipher),
                        expected_runes=len(expected), mismatch_count=len(mismatches),
                        mismatch_ordinals=mismatches, exact=mismatches == [],
                        inverse_roundtrip=inverse == cipher,
                        decoded_sha256=stable_digest(decoded), expected_sha256=stable_digest(expected),
                        status="passed" if not mismatches and inverse == cipher else "negative")
        write_json(run / "observed.json", observed)
        controls = []
        for a, b in pairs:
            result = affine(cipher, a, b)
            differences = [i for i, (actual, target) in enumerate(zip(result, expected)) if actual != target]
            controls.append(dict(a=a, b=b, mismatch_count=len(differences),
                                 first_mismatch=differences[0] if differences else None,
                                 status="negative" if differences else "control_collision"))
        controls_ok = all(row["status"] == "negative" for row in controls)
        write_json(run / "random-controls.json", dict(seed=CONTROL_SEED, requested=CONTROL_COUNT,
                                                       completed=len(controls), controls=controls,
                                                       all_negative=controls_ok))
        summary = dict(status="passed" if observed["status"] == "passed" and controls_ok else "negative",
                       verification_status="passed", observed=observed,
                       random_controls=dict(count=len(controls), all_negative=controls_ok,
                                            minimum_mismatches=min(row["mismatch_count"] for row in controls)),
                       coverage=dict(known_page="LP1/06", rune_positions=len(cipher),
                                     random_affine_controls=len(controls),
                                     unsolved_page_candidates=[]),
                       interpretation="Known-page source regression only; no LP2 page was searched or solved.",
                       limitation="The source-reported method and its Plaintext block share one archived document; image-level independent glyph audit remains outside this run.")
        write_json(run / "summary.json", summary)
        record["status"] = summary["status"]
        record["result"] = dict(mismatch_count=observed["mismatch_count"],
                                 inverse_roundtrip=observed["inverse_roundtrip"],
                                 random_controls=len(controls), controls_ok=controls_ok)
        record["actual_coverage"] = summary["coverage"]
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H012 execution")
        record["reproduction_bundle"] = archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    except Exception as exc:
        record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
        record["error"] = repr(exc)
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    write_json(run / "record.json", record)
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"],
                      "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
