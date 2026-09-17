"""Run H010: a bounded full-corpus multiplicative prime-clock diagnostic."""
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

SPEC_PATH = ROOT / "hypotheses/H010-multiplicative-prime-clock-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
BRANCHES = (
    ("continuous_f_free", True, False),
    ("continuous_f_consume", True, True),
    ("page_reset_f_free", False, False),
    ("page_reset_f_consume", False, True),
)
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011001
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


def simple_primes(count):
    """Trial-division stream used by the independent validation path."""
    if type(count) is not int or count < 1:
        raise ValueError("Prime count must be positive")
    result, candidate = [], 2
    while len(result) < count:
        if all(candidate % divisor for divisor in range(2, math.isqrt(candidate) + 1)):
            result.append(candidate)
        candidate += 1
    return result


def sieve_primes(count):
    """Different implementation used for the observed decoder."""
    bound = max(128, count * 20)
    sieve = bytearray(b"\x01") * (bound + 1)
    sieve[:2] = b"\x00\x00"
    for n in range(2, math.isqrt(bound) + 1):
        if sieve[n]:
            sieve[n * n:bound + 1:n] = b"\x00" * (((bound - n * n) // n) + 1)
    primes = [n for n, flag in enumerate(sieve) if flag]
    if len(primes) < count:
        raise ValueError("Sieve bound insufficient")
    return primes[:count]


def weights_from_training():
    train = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
    counts = [train.count(i) for i in range(29)]
    weights = [math.log((count + 1) / (len(train) + 29)) for count in counts]
    return train, counts, weights


def load_pages():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    pages = []
    for page in corpus["pages"]:
        indices = [RUNES.index(char) for char in page["raw"] if char in RUNES]
        pages.append(dict(page=page["page"], page_number=page["page_number"], indices=indices,
                          raw_sha256=page["raw_sha256"], rune_count=len(indices)))
    if [p["page"] for p in pages] != [f"LP2/{i}" for i in range(56)]:
        raise ValueError("Corpus page order is not LP2/0..55")
    if len([p for p in pages if p["indices"]]) != 55 or [p["page"] for p in pages if not p["indices"]] != ["LP2/50"]:
        raise ValueError("Unexpected applicability set")
    if sum(len(p["indices"]) for p in pages) != 12956:
        raise ValueError("Unexpected rune count")
    return pages


def decode_page_candidate(cipher, start_clock, primes, consume_zero):
    values, clock = [], start_clock
    for cipher_value in cipher:
        if cipher_value == 0:
            values.append(0)
            if consume_zero:
                clock += 1
            continue
        multiplier = pow(2, primes[clock] - 1, 29)
        values.append((cipher_value * pow(multiplier, 27, 29)) % 29)
        clock += 1
    return values, clock


def decode_pages_candidate(pages, primes):
    rows = []
    for branch_name, continuous, consume_zero in BRANCHES:
        clock = 0
        for page in pages:
            start = clock if continuous else 0
            plaintext, terminal = decode_page_candidate(page["indices"], start, primes, consume_zero)
            clock = terminal if continuous else clock
            rows.append(dict(page=page["page"], branch=branch_name,
                             start_clock=start, terminal_clock=terminal,
                             plaintext=plaintext))
    return rows


def decode_page_independent(cipher, start_clock, primes, consume_zero):
    """Independent arithmetic spelling of the registered model."""
    plaintext = []
    clock = start_clock
    for value in cipher:
        if value == 0:
            plaintext.append(0)
            clock = clock + 1 if consume_zero else clock
        else:
            exponent = primes[clock] - 1
            multiplier = pow(2, exponent, 29)
            inverse = pow(multiplier, 29 - 2, 29)
            plaintext.append((value * inverse) % 29)
            clock += 1
    return plaintext, clock


def validate_rows(pages, rows, primes, weights):
    expected_keys = {(page["page"], branch[0]) for page in pages for branch in BRANCHES if page["indices"]}
    actual_keys = {(row["page"], row["branch"]) for row in rows}
    if actual_keys != expected_keys:
        raise ValueError("Observed branch coverage mismatch")
    page_map = {page["page"]: page for page in pages}
    branch_clocks = {branch[0]: 0 for branch in BRANCHES}
    checks = 0
    for row in rows:
        page = page_map[row["page"]]
        _, continuous, consume_zero = next(branch for branch in BRANCHES if branch[0] == row["branch"])
        expected_start = branch_clocks[row["branch"]] if continuous else 0
        if row["start_clock"] != expected_start:
            raise ValueError("Clock start mismatch")
        reference, terminal = decode_page_independent(page["indices"], expected_start, primes, consume_zero)
        if row["plaintext"] != reference or row["terminal_clock"] != terminal:
            raise ValueError("Independent decode mismatch")
        reencrypted, clock = [], expected_start
        for plain in reference:
            if plain == 0:
                reencrypted.append(0)
                if consume_zero:
                    clock += 1
            else:
                multiplier = pow(2, primes[clock] - 1, 29)
                reencrypted.append((plain * multiplier) % 29)
                clock += 1
        if reencrypted != page["indices"] or clock != terminal:
            raise ValueError("Multiplicative re-encryption mismatch")
        if continuous:
            branch_clocks[row["branch"]] = terminal
        score = sum(weights[value] for value in reference) / len(reference)
        row["score"] = score
        row["zero_count"] = reference.count(0)
        checks += len(reference)
    return dict(status="passed", rows=len(rows), rune_checks=checks)


def scores_for_pages(pages, primes, weights):
    rows = decode_pages_candidate(pages, primes)
    values = []
    for row in rows:
        score = sum(weights[value] for value in row["plaintext"]) / len(row["plaintext"])
        values.append(score)
        row["score"] = score
        row["zero_count"] = row["plaintext"].count(0)
    return rows, values


def standardize(observed, controls):
    if not controls:
        raise ValueError("No completed control rows")
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
        z = [(value - mean) / std if std > 0 else 0.0
             for value, mean, std in zip(row, means, stds)]
        control_max.append(max(z) if z else 0.0)
    p_values = []
    for index, z in enumerate(observed_z):
        if stds[index] == 0:
            p_values.append(1.0)
        else:
            p_values.append((1 + sum(control >= z - TIE_TOLERANCE for control in control_max)) /
                            (len(control_max) + 1))
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
    started = dt.datetime.now(dt.timezone.utc)
    wall_started = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis="H010-multiplicative-prime-clock-v1",
                  attempt="auto-cycle R002", status="running", started_at_utc=started.isoformat(),
                  python=sys.version, executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, controls_completed=0, unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    log_lines = []

    def log(message):
        log_lines.append(message)
        (run / "runner.stdout.txt").write_text("\n".join(log_lines) + "\n", encoding="utf8")
        print(message)

    control_rows = []
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        pages = load_pages()
        train, counts, weights = weights_from_training()
        total_runes = sum(len(page["indices"]) for page in pages)
        primes = sieve_primes(total_runes + 1)
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH),
                      data_versions={"corpus": sha256(CORPUS_PATH), "training": sha256(TRAIN_PATH)},
                      source_files_verified=source_count, code_version=snapshot,
                      page_order=[page["page"] for page in pages],
                      applicable_pages=[page["page"] for page in pages if page["indices"]],
                      excluded_pages=[page["page"] for page in pages if not page["indices"]],
                      rune_count=total_runes, training_rune_count=len(train), training_counts=counts,
                      scorer_weights=weights, branches=[branch[0] for branch in BRANCHES],
                      control_replicates=CONTROL_REPLICATES, control_seed=CONTROL_SEED,
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE,
                      total_wall_seconds=WALL_SECONDS)
        write_json(run / "frozen.json", frozen)
        record.update(frozen_sha256=sha256(run / "frozen.json"), source_files_verified=source_count)
        write_json(run / "record.json", record)

        applicable_pages = [page for page in pages if page["indices"]]
        observed_rows, observed_scores = scores_for_pages(applicable_pages, primes, weights)
        validation = validate_rows(applicable_pages, observed_rows, simple_primes(total_runes + 1), weights)
        write_json(run / "independent-verification.json", validation)
        write_json(run / "observed.json", dict(rows=observed_rows,
                                                score_vector=observed_scores,
                                                score_vector_sha256=stable_digest(observed_scores)))
        record["observed_rows"] = len(observed_rows)
        record["observed_rune_checks"] = validation["rune_checks"]
        write_json(run / "record.json", record)
        log(f"observed rows={len(observed_rows)} rune_checks={validation['rune_checks']}")

        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() - wall_started > WALL_SECONDS:
                raise TimeoutError(f"H010 wall budget exceeded after {len(control_rows)} controls")
            shuffled_pages = []
            for page in applicable_pages:
                values = list(page["indices"])
                rng.shuffle(values)
                shuffled_pages.append(dict(page=page["page"], page_number=page["page_number"],
                                           indices=values, raw_sha256=page["raw_sha256"],
                                           rune_count=len(values)))
            _, scores = scores_for_pages(shuffled_pages, primes, weights)
            control_rows.append(scores)
            record["controls_completed"] = len(control_rows)
            if replicate % 100 == 0:
                log(f"controls={replicate}")
                write_json(run / "record.json", record)
        control_artifact = dict(schema=1, algorithm="within-page permutation maxT for H010",
                                control_seed=CONTROL_SEED, requested=CONTROL_REPLICATES,
                                completed=len(control_rows), score_cell_order=[
                                    f"{row['page']}::{row['branch']}" for row in observed_rows
                                ], controls=control_rows)
        write_json(run / "control-scores.json", control_artifact)
        stats = standardize(observed_scores, control_rows)
        stat_rows = []
        for row, z, p in zip(observed_rows, stats["observed_z"], stats["p_adjusted"]):
            stat_rows.append(dict(page=row["page"], branch=row["branch"], score=row["score"],
                                  z=z, p_adjusted=p, status="inconclusive" if p <= ALPHA else "negative"))
        leads = [row for row in stat_rows if row["status"] == "inconclusive"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"], row["branch"]))[:10]
        summary = dict(status="inconclusive" if leads else "negative",
                       verification_status="passed", controls_completed=len(control_rows),
                       coverage=dict(pages=55, runes=total_runes, branches=4, cells=len(observed_rows),
                                     control_replicates=len(control_rows), unsolved_page_candidates=[]),
                       leads=leads, strongest=strongest,
                       standardization=dict(observed_z=stats["observed_z"],
                                            p_adjusted=stats["p_adjusted"],
                                            control_max_z=stats["control_max_z"]),
                       interpretation="A lead is a score-based diagnostic only; no page is accepted as decrypted.",
                       negative_scope="Only H010's fixed base-2 prime exponent, four clock/F branches, unigram score and within-page permutation null.")
        write_json(run / "statistics.json", summary)
        record["status"] = summary["status"]
        record["result"] = dict(leads=len(leads), strongest=strongest[:3],
                                 controls_completed=len(control_rows))
        record["actual_coverage"] = summary["coverage"]
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H010 execution")
        record["reproduction_bundle"] = archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    except Exception as exc:
        record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
        record["error"] = repr(exc)
        record["controls_completed"] = len(control_rows)
        if control_rows:
            write_json(run / "control-scores.partial.json", dict(completed=len(control_rows), controls=control_rows))
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
        log(f"{record['status']}: {record['error']}")
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    write_json(run / "record.json", record)
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"],
                      "controls_completed": record.get("controls_completed"),
                      "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"negative", "inconclusive", "passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
