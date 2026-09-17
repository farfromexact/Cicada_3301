"""Run H014: source-gated FIRFUMFERENFE Vigenere transfer diagnostic."""
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
from lp_lab.synthetic import encode_text

SPEC_PATH = ROOT / "hypotheses/H014-circumference-transfer-v1.json"
SOURCE_PATH = ROOT / "sources/clues-v1/ibot/liber_primus/markdown/14.md"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
KEY = (0, 10, 4, 0, 1, 19, 0, 18, 4, 18, 9, 0, 18)
SOURCE_SKIP_COORDINATES = (65, 76)
BRANCHES = (
    ("continuous_f_consume", True, True),
    ("continuous_f_free", True, False),
    ("page_reset_f_consume", False, True),
    ("page_reset_f_free", False, False),
)
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011401
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


def weights_from_training():
    training = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
    counts = [training.count(value) for value in range(29)]
    total = len(training)
    return training, counts, [math.log((count + 1) / (total + 29)) for count in counts]


def load_source_gate():
    source = SOURCE_PATH.read_text(encoding="utf8")
    blocks = re.findall(r"```[^\r\n]*\r?\n(.*?)```", source, re.S)
    if len(blocks) < 2:
        raise ValueError("LP1/14-15 source has no registered one-line block")
    cipher = indices(blocks[1])
    expected = reference_indices(SOURCE_PATH)
    if len(cipher) != len(expected) or len(cipher) != 226:
        raise ValueError("LP1/14-15 source/reference length changed")
    match = re.search(r"Enter a sentence to translate:\s*\r?\n > ([^\r\n]+)", source)
    if not match or indices(match.group(1)) != cipher:
        raise ValueError("Source tool-input line disagrees with the registered ciphertext block")
    tool_line = match.group(1)
    skip_ordinals = []
    for coordinate in SOURCE_SKIP_COORDINATES:
        if not 1 <= coordinate <= len(tool_line) or tool_line[coordinate - 1] not in RUNES:
            raise ValueError(f"Source skip coordinate is not a rune: {coordinate}")
        skip_ordinals.append(sum(char in RUNES for char in tool_line[:coordinate - 1]))
    return dict(source=source, cipher=cipher, expected=expected, tool_line=tool_line,
                skip_coordinates=list(SOURCE_SKIP_COORDINATES), skip_ordinals=skip_ordinals,
                cipher_block_sha256=hashlib.sha256(blocks[1].encode("utf8")).hexdigest())


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


def decrypt(values, start_clock, consume_zero, skips=()):
    skip_set = set(skips)
    plain, clock = [], start_clock
    for ordinal, cipher in enumerate(values):
        if ordinal in skip_set or (cipher == 0 and not skips and not consume_zero):
            plain.append(0 if not skips else cipher)
            continue
        plain.append((cipher - KEY[clock % len(KEY)]) % 29)
        clock += 1
    return plain, clock


def encrypt(values, start_clock, consume_zero, skips=()):
    skip_set = set(skips)
    cipher, clock = [], start_clock
    for ordinal, plain in enumerate(values):
        if ordinal in skip_set:
            cipher.append(plain)
            continue
        cipher.append((plain + KEY[clock % len(KEY)]) % 29)
        clock += 1
    return cipher, clock


def known_gate(gate):
    skips = tuple(gate["skip_ordinals"])
    decoded, terminal = decrypt(gate["cipher"], 0, False, skips)
    mismatches = [i for i, (actual, target) in enumerate(zip(decoded, gate["expected"]))
                  if actual != target]
    roundtrip, inverse_terminal = encrypt(decoded, 0, False, skips)
    return dict(input_runes=len(gate["cipher"]), expected_runes=len(gate["expected"]),
                skip_coordinates=list(gate["skip_coordinates"]), skip_ordinals=list(skips), key_indices=list(KEY),
                mismatch_count=len(mismatches), mismatch_ordinals=mismatches,
                exact=not mismatches, terminal_clock=terminal,
                inverse_roundtrip=roundtrip == gate["cipher"],
                inverse_terminal_clock=inverse_terminal,
                status="passed" if not mismatches and roundtrip == gate["cipher"] else "negative")


def score(values, weights):
    return sum(weights[value] for value in values) / len(values) if values else None


def decode_pages(pages, weights):
    applicable = [page for page in pages if page["indices"]]
    rows = []
    for branch, continuous, consume_zero in BRANCHES:
        clock = 0
        for page in applicable:
            start = clock if continuous else 0
            plain, terminal = decrypt(page["indices"], start, consume_zero)
            if continuous:
                clock = terminal
            rows.append(dict(page=page["page"], branch=branch, start_clock=start,
                             terminal_clock=terminal, rune_count=len(plain),
                             decoded_indices=plain, score=score(plain, weights)))
    return rows


def validate_rows(pages, rows, weights):
    applicable = [page for page in pages if page["indices"]]
    page_map = {page["page"]: page for page in applicable}
    expected_keys = {(page["page"], branch[0]) for branch in BRANCHES for page in applicable}
    if {(row["page"], row["branch"]) for row in rows} != expected_keys:
        raise ValueError("Observed branch coverage mismatch")
    clocks = {branch[0]: 0 for branch in BRANCHES}
    rune_checks = 0
    for row in rows:
        page = page_map[row["page"]]
        _, continuous, consume_zero = next(branch for branch in BRANCHES if branch[0] == row["branch"])
        start = clocks[row["branch"]] if continuous else 0
        plain, terminal = decrypt_independent(page["indices"], start, consume_zero)
        if row["start_clock"] != start or row["terminal_clock"] != terminal or row["decoded_indices"] != plain:
            raise ValueError(f"Independent decode mismatch: {row['page']} {row['branch']}")
        skip_positions = tuple(i for i, value in enumerate(page["indices"])
                               if value == 0) if not consume_zero else ()
        cipher, inverse_terminal = encrypt_independent(plain, start, consume_zero, skip_positions)
        if cipher != page["indices"] or inverse_terminal != terminal:
            raise ValueError(f"Independent roundtrip mismatch: {row['page']} {row['branch']}")
        expected_score = sum(weights[value] for value in plain) / len(plain)
        if not math.isclose(row["score"], expected_score, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"Independent score mismatch: {row['page']} {row['branch']}")
        if continuous:
            clocks[row["branch"]] = terminal
        rune_checks += len(plain)
    return dict(status="passed", rows=len(rows), rune_checks=rune_checks,
                exact_roundtrips=True)


def decrypt_independent(values, start_clock, consume_zero):
    plain, clock = [], start_clock
    for cipher in values:
        if cipher == 0 and not consume_zero:
            plain.append(0)
        else:
            plain.append((cipher - KEY[clock % 13]) % 29)
            clock += 1
    return plain, clock


def encrypt_independent(values, start_clock, consume_zero, skips=()):
    cipher, clock = [], start_clock
    skip_set = set(skips)
    for ordinal, plain in enumerate(values):
        if ordinal in skip_set:
            cipher.append(plain)
            continue
        cipher.append((plain + KEY[clock % 13]) % 29)
        clock += 1
    return cipher, clock


def shuffled_pages(pages, rng):
    return [dict(page=page["page"], indices=randomized(page["indices"], rng))
            for page in pages if page["indices"]]


def randomized(values, rng):
    result = list(values)
    rng.shuffle(result)
    return result


def control_score_rows(pages, weights, started):
    controls = []
    applicable = [page for page in pages if page["indices"]]
    rng = random.Random(CONTROL_SEED)
    for replicate in range(1, CONTROL_REPLICATES + 1):
        if time.monotonic() - started > WALL_SECONDS:
            raise TimeoutError(f"H014 wall budget exceeded after {replicate - 1} controls")
        shuffled = shuffled_pages(applicable, rng)
        rows = decode_pages([dict(page=p["page"], indices=p["indices"], raw="",
                                  raw_sha256="", page_number=0, source="", image_path="")
                             for p in shuffled], weights)
        controls.append([row["score"] for row in rows])
    return controls


def standardize(observed, controls):
    if not controls:
        raise ValueError("No controls")
    columns = len(observed)
    means, stds = [], []
    for index in range(columns):
        values = [observed[index]] + [row[index] for row in controls]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(math.sqrt(variance))
    observed_z = [(value - mean) / std if std > 0 else 0.0
                  for value, mean, std in zip(observed, means, stds)]
    control_max = []
    for row in controls:
        control_max.append(max((value - mean) / std if std > 0 else 0.0
                               for value, mean, std in zip(row, means, stds)))
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
    record = dict(schema=1, hypothesis="H014-circumference-transfer-v1",
                  attempt="auto-cycle R006", status="running",
                  started_at_utc=started_at.isoformat(), python=sys.version,
                  executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, controls_completed=0,
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        gate = load_source_gate()
        pages = load_pages()
        training, counts, weights = weights_from_training()
        known = known_gate(gate)
        if known["status"] != "passed":
            raise ValueError(f"Known-page gate failed: {known['mismatch_count']} mismatches")
        applicable = [page for page in pages if page["indices"]]
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH),
                      data_versions={"source": sha256(SOURCE_PATH), "corpus": sha256(CORPUS_PATH),
                                     "training": sha256(TRAIN_PATH)},
                      source_files_verified=source_count, code_version=snapshot,
                      key_indices=list(KEY), source_skip_coordinates=gate["skip_coordinates"],
                      source_skip_ordinals=gate["skip_ordinals"],
                      known_gate=known, page_order=[page["page"] for page in pages],
                      applicable_pages=[page["page"] for page in applicable],
                      excluded_pages=[page["page"] for page in pages if not page["indices"]],
                      rune_count=sum(page["rune_count"] for page in pages),
                      training_rune_count=len(training), training_counts=counts,
                      scorer_weights=weights, branches=[branch[0] for branch in BRANCHES],
                      control_replicates=CONTROL_REPLICATES, control_seed=CONTROL_SEED,
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE,
                      total_wall_seconds=WALL_SECONDS,
                      raw_page_sha256={page["page"]: page["raw_sha256"] for page in pages})
        write_json(run / "frozen.json", frozen)
        record.update(frozen_sha256=sha256(run / "frozen.json"), source_files_verified=source_count,
                      known_gate=known)
        write_json(run / "record.json", record)

        observed_rows = decode_pages(pages, weights)
        validation = validate_rows(pages, observed_rows, weights)
        write_json(run / "independent-verification.json", validation)
        write_json(run / "known-gate.json", known)
        write_json(run / "observed.json", dict(rows=observed_rows,
                                                score_vector=[row["score"] for row in observed_rows],
                                                score_vector_sha256=stable_digest([row["score"] for row in observed_rows])))
        record.update(observed_rows=len(observed_rows), observed_rune_checks=validation["rune_checks"])
        write_json(run / "record.json", record)

        controls = control_score_rows(pages, weights, wall_started)
        record["controls_completed"] = len(controls)
        write_json(run / "control-scores.json", dict(schema=1, algorithm="within-page permutation maxT",
                                                      seed=CONTROL_SEED, requested=CONTROL_REPLICATES,
                                                      completed=len(controls),
                                                      cell_order=[f"{row['page']}::{row['branch']}" for row in observed_rows],
                                                      score_rows=controls))
        stats = standardize([row["score"] for row in observed_rows], controls)
        stat_rows = []
        for row, z, p in zip(observed_rows, stats["observed_z"], stats["p_adjusted"]):
            stat_rows.append(dict(page=row["page"], branch=row["branch"], rune_count=row["rune_count"],
                                  score=row["score"], z=z, p_adjusted=p,
                                  status="inconclusive" if p <= ALPHA else "negative"))
        leads = [row for row in stat_rows if row["status"] == "inconclusive"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"], row["branch"]))[:10]
        summary = dict(status="inconclusive" if leads else "negative", known_gate=known,
                       verification_status="passed", controls_completed=len(controls),
                       coverage=dict(pages=55, applicable_pages=55, excluded_pages=["LP2/50"],
                                     runes=12956, branches=4, cells=len(observed_rows),
                                     control_replicates=len(controls), unsolved_page_candidates=[row["page"] for row in leads]),
                       leads=leads, strongest=strongest,
                       statistics=dict(observed_z=stats["observed_z"], p_adjusted=stats["p_adjusted"],
                                       control_max_z=stats["control_max_z"]),
                       interpretation="Source-gated fixed-key transfer diagnostic; a lead is not an LP2 decryption.",
                       negative_scope="Only H014's FIRFUMFERENFE key, subtractive direction, four clock/F branches, unigram score and permutation null.",
                       limitation="No independent LP2 plaintext or image-level glyph audit is available.")
        write_json(run / "statistics.json", summary)
        record["status"] = summary["status"]
        record["result"] = dict(leads=len(leads), strongest=strongest[:3], controls_completed=len(controls))
        record["actual_coverage"] = summary["coverage"]
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H014 execution")
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
