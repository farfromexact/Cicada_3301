"""Run H015: fixed finite-field inversion diagnostic over LP2."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import platform
import random
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES
from lp_lab.synthetic import encode_text

SPEC_PATH = ROOT / "hypotheses/H015-mobius-inversion-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
CONTROL_COUNT = 256
CONTROL_SEED = 33011501
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf8")


def stable_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def inversion(value):
    if type(value) is not int or not 0 <= value < 29:
        raise ValueError("Rune ordinal must be in 0..28")
    return 0 if value == 0 else pow(value, 27, 29)


def invert_values(values):
    return [inversion(value) for value in values]


def transform_raw(raw):
    return "".join(RUNES[inversion(RUNES.index(char))] if char in RUNES else char
                   for char in raw)


def load_pages():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    pages = []
    for page in corpus["pages"]:
        raw = page["raw"]
        values = [RUNES.index(char) for char in raw if char in RUNES]
        pages.append(dict(page=page["page"], page_number=page["page_number"], raw=raw,
                          raw_sha256=page["raw_sha256"], indices=values,
                          rune_count=len(values), source=page["source"],
                          image_path=page["image_path"]))
    if [page["page"] for page in pages] != [f"LP2/{i}" for i in range(56)]:
        raise ValueError("Corpus page order is not LP2/0..55")
    if [page["page"] for page in pages if not page["indices"]] != ["LP2/50"]:
        raise ValueError("Unexpected inapplicable page set")
    if len([page for page in pages if page["indices"]]) != 55:
        raise ValueError("Unexpected number of applicable pages")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("Unexpected rune count")
    return pages


def weights_from_training():
    training = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
    counts = [training.count(value) for value in range(29)]
    total = len(training)
    return training, counts, [math.log((count + 1) / (total + 29)) for count in counts]


def random_control_maps():
    rng = random.Random(CONTROL_SEED)
    registered = tuple(inversion(value) for value in range(29))
    maps = []
    seen = {registered}
    while len(maps) < CONTROL_COUNT:
        nonzero = list(range(1, 29))
        rng.shuffle(nonzero)
        mapping = tuple([0] + nonzero)
        if mapping not in seen:
            maps.append(mapping)
            seen.add(mapping)
    return maps


def score(values, weights):
    return sum(weights[value] for value in values) / len(values) if values else None


def observed_rows(pages, weights):
    rows = []
    for page in pages:
        decoded = invert_values(page["indices"])
        rows.append(dict(page=page["page"], rune_count=len(decoded), decoded_indices=decoded,
                         score=score(decoded, weights), decoded_raw=transform_raw(page["raw"])))
    return rows


def independent_validate(pages, rows, weights):
    page_map = {page["page"]: page for page in pages if page["indices"]}
    if {row["page"] for row in rows} != set(page_map):
        raise ValueError("Observed page coverage mismatch")
    rune_checks = 0
    for row in rows:
        page = page_map[row["page"]]
        expected = [0 if value == 0 else pow(value, 27, 29) for value in page["indices"]]
        if row["decoded_indices"] != expected:
            raise ValueError(f"Independent inversion mismatch: {row['page']}")
        if [0 if value == 0 else pow(value, 27, 29) for value in expected] != page["indices"]:
            raise ValueError(f"Involution roundtrip mismatch: {row['page']}")
        expected_score = sum(weights[value] for value in expected) / len(expected)
        if not math.isclose(row["score"], expected_score, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"Independent score mismatch: {row['page']}")
        rune_checks += len(expected)
    return dict(status="passed", pages=len(rows), rune_checks=rune_checks,
                exact_involution_roundtrip=True)


def control_scores(pages, mappings, weights, started):
    controls = []
    applicable = [page for page in pages if page["indices"]]
    for count, mapping in enumerate(mappings, start=1):
        if time.monotonic() - started > WALL_SECONDS:
            raise TimeoutError(f"H015 wall budget exceeded after {count - 1} controls")
        controls.append([score([mapping[value] for value in page["indices"]], weights)
                         for page in applicable])
    return controls


def standardize(observed, controls):
    means, stds = [], []
    for index in range(len(observed)):
        values = [observed[index]] + [row[index] for row in controls]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(math.sqrt(variance))
    observed_z = [(value - mean) / std if std > 0 else 0.0
                  for value, mean, std in zip(observed, means, stds)]
    control_max = [max((value - mean) / std if std > 0 else 0.0
                       for value, mean, std in zip(row, means, stds)) for row in controls]
    p_values = [(1 + sum(max_z >= z - TIE_TOLERANCE for max_z in control_max)) /
                (len(control_max) + 1) if std > 0 else 1.0
                for z, std in zip(observed_z, stds)]
    return dict(means=means, stds=stds, observed_z=observed_z,
                control_max_z=control_max, p_adjusted=p_values)


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
    started_at = dt.datetime.now(dt.timezone.utc)
    wall_started = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis="H015-mobius-inversion-v1",
                  attempt="auto-cycle R007", status="running",
                  started_at_utc=started_at.isoformat(), python=sys.version,
                  executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, controls_completed=0,
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        pages = load_pages()
        training, counts, weights = weights_from_training()
        mappings = random_control_maps()
        applicable = [page for page in pages if page["indices"]]
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH),
                      data_versions={"corpus": sha256(CORPUS_PATH), "training": sha256(TRAIN_PATH)},
                      source_files_verified=source_count, code_version=snapshot,
                      fixed_map=[inversion(value) for value in range(29)],
                      fixed_map_formula="f(0)=0; f(x)=x^27 mod29 for x=1..28",
                      page_order=[page["page"] for page in pages],
                      applicable_pages=[page["page"] for page in applicable],
                      excluded_pages=[page["page"] for page in pages if not page["indices"]],
                      rune_count=sum(page["rune_count"] for page in pages),
                      training_rune_count=len(training), training_counts=counts,
                      scorer_weights=weights, control_seed=CONTROL_SEED,
                      control_count=CONTROL_COUNT, control_maps=[list(mapping) for mapping in mappings],
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE,
                      total_wall_seconds=WALL_SECONDS,
                      raw_page_sha256={page["page"]: page["raw_sha256"] for page in pages})
        write_json(run / "frozen.json", frozen)
        record.update(frozen_sha256=sha256(run / "frozen.json"), source_files_verified=source_count)
        write_json(run / "record.json", record)

        observed = observed_rows(applicable, weights)
        validation = independent_validate(applicable, observed, weights)
        write_json(run / "independent-verification.json", validation)
        write_json(run / "decoded.json", dict(formula="f(0)=0; f(x)=x^27 mod29",
                                               pages=observed,
                                               score_vector=[row["score"] for row in observed],
                                               score_vector_sha256=stable_digest([row["score"] for row in observed])))
        record.update(observed_pages=len(observed), observed_rune_checks=validation["rune_checks"])
        write_json(run / "record.json", record)

        controls = control_scores(pages, mappings, weights, wall_started)
        record["controls_completed"] = len(controls)
        write_json(run / "control-scores.json", dict(schema=1,
                                                      algorithm="random zero-preserving permutation controls",
                                                      seed=CONTROL_SEED, requested=CONTROL_COUNT,
                                                      completed=len(controls),
                                                      page_order=[page["page"] for page in applicable],
                                                      score_rows=controls))
        stats = standardize([row["score"] for row in observed], controls)
        stat_rows = []
        for row, z, p in zip(observed, stats["observed_z"], stats["p_adjusted"]):
            stat_rows.append(dict(page=row["page"], rune_count=row["rune_count"], score=row["score"],
                                  z=z, p_adjusted=p,
                                  status="inconclusive" if p <= ALPHA else "negative"))
        leads = [row for row in stat_rows if row["status"] == "inconclusive"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"]))[:10]
        summary = dict(status="inconclusive" if leads else "negative",
                       verification_status="passed", controls_completed=len(controls),
                       coverage=dict(pages=55, applicable_pages=55, excluded_pages=["LP2/50"],
                                     runes=12956, cells=len(observed), random_controls=len(controls),
                                     unsolved_page_candidates=[row["page"] for row in leads]),
                       leads=leads, strongest=strongest,
                       statistics=dict(observed_z=stats["observed_z"], p_adjusted=stats["p_adjusted"],
                                       control_max_z=stats["control_max_z"]),
                       interpretation="Fixed finite-field inversion diagnostic only; a lead is not an LP2 decryption.",
                       negative_scope="Only H015's f(0)=0, f(x)=x^-1 mod29 map, unigram score and random zero-preserving permutation null.",
                       limitation="No independent LP2 plaintext or image-level glyph audit is available.")
        write_json(run / "statistics.json", summary)
        record["status"] = summary["status"]
        record["result"] = dict(leads=len(leads), strongest=strongest[:3], controls_completed=len(controls))
        record["actual_coverage"] = summary["coverage"]
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H015 execution")
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
                      "controls_completed": record.get("controls_completed"),
                      "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
