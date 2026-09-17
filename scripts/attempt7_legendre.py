"""Run H011: Legendre-projection lag statistics over all applicable LP2 pages."""
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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES
from lp_lab.structure_inputs import prepare_page
from lp_lab.synthetic import encode_text

SPEC_PATH = ROOT / "hypotheses/H011-legendre-projection-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
HELDOUT_PATH = ROOT / "data/synthetic/heldout.txt"
LAGS = tuple(range(1, 29))
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011101
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


def chi(value):
    if value == 0:
        return 0
    if type(value) is not int or not 0 <= value < 29:
        raise ValueError("Rune value must be in 0..28")
    return 1 if pow(value, 14, 29) == 1 else -1


CHI_LOOKUP = np.asarray([chi(value) for value in range(29)], dtype=np.int8)


def load_pages():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    prepared = [prepare_page(page) for page in corpus["pages"]]
    if [page["page"] for page in prepared] != [f"LP2/{i}" for i in range(56)]:
        raise ValueError("Corpus page order is not LP2/0..55")
    if len([page for page in prepared if page["indices"]]) != 55:
        raise ValueError("Unexpected number of rune-bearing pages")
    if [page["page"] for page in prepared if not page["indices"]] != ["LP2/50"]:
        raise ValueError("Unexpected inapplicable page")
    if sum(len(page["indices"]) for page in prepared) != 12956:
        raise ValueError("Unexpected rune count")
    return prepared


def vector_statistics(pages, replacements=None):
    """Vectorized measurement used for the main observed/control path."""
    if replacements is None:
        replacements = [page["indices"] for page in pages]
    if len(replacements) != len(pages):
        raise ValueError("Replacement page count mismatch")
    result = []
    for page, replacement in zip(pages, replacements):
        values = np.asarray(replacement, dtype=np.int64)
        original = np.asarray(page["indices"], dtype=np.int64)
        groups = np.asarray(page["groups"], dtype=np.int64)
        if values.shape != original.shape or np.any((values < 0) | (values >= 29)):
            raise ValueError("Replacement sequence shape or range mismatch")
        projected = CHI_LOOKUP[values]
        for lag in LAGS:
            numerator = 0
            denominator = 0
            for start, end in page["segments"]:
                if end - start > lag:
                    numerator += int(np.dot(projected[start:end - lag],
                                            projected[start + lag:end]))
                    denominator += end - start - lag
            if denominator == 0:
                result.append(0.0)
                continue
            result.append(abs(float(numerator) / denominator))
    return result


def manual_statistics(pages):
    """Independent pure-Python observed replay, no NumPy operations."""
    result = []
    for page in pages:
        values = page["indices"]
        groups = page["groups"]
        projected = [chi(value) for value in values]
        for lag in LAGS:
            products = [projected[i] * projected[i + lag]
                        for i in range(len(values) - lag)
                        if groups[i] == groups[i + lag]]
            result.append(abs(sum(products) / len(products)) if products else 0.0)
    return result


def synthetic_sensitivity():
    heldout = encode_text(HELDOUT_PATH.read_text(encoding="utf8"))
    if len(heldout) < 256:
        raise ValueError("Heldout text too short for sensitivity")
    plaintext = heldout[:256]
    plaintext[0] = 0
    primes = []
    candidate = 2
    while len(primes) < len(plaintext):
        if all(candidate % divisor for divisor in range(2, math.isqrt(candidate) + 1)):
            primes.append(candidate)
        candidate += 1
    cipher = [(value * pow(2, primes[index] - 1, 29)) % 29
              for index, value in enumerate(plaintext)]
    plain_projection = [chi(value) for value in plaintext]
    cipher_projection = [chi(value) for value in cipher]
    later_equal = all(a == b for a, b in zip(plain_projection[1:], cipher_projection[1:]))
    first_expected = cipher_projection[0] == 0
    return dict(status="passed" if later_equal and first_expected else "negative",
                length=len(plaintext), first_plaintext_value=plaintext[0],
                later_positions=len(plaintext) - 1,
                later_projection_equal=later_equal,
                first_position_zero_preserved=first_expected,
                plaintext_sha256=stable_digest(plaintext),
                cipher_projection_sha256=stable_digest(cipher_projection))


def standardize(observed, controls):
    if len(observed) != 55 * len(LAGS) or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected projection matrix shape")
    observed_array = np.asarray(observed, dtype=float)
    control_array = np.asarray(controls, dtype=float)
    values = np.vstack((observed_array, control_array))
    means = values.mean(axis=0)
    stds = values.std(axis=0)
    observed_z = np.divide(observed_array - means, stds,
                           out=np.zeros_like(observed_array), where=stds > 0)
    control_z = np.divide(control_array - means, stds,
                          out=np.zeros_like(control_array), where=stds > 0)
    control_max = control_z.max(axis=1)
    p_adjusted = np.asarray([
        1.0 if stds[index] == 0 else
        (1 + np.count_nonzero(control_max >= z - TIE_TOLERANCE)) / (len(control_max) + 1)
        for index, z in enumerate(observed_z)
    ])
    return dict(means=means.tolist(), stds=stds.tolist(),
                observed_z=observed_z.tolist(), control_max_z=control_max.tolist(),
                p_adjusted=p_adjusted.tolist())


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
    record = dict(schema=1, hypothesis="H011-legendre-projection-v1",
                  attempt="auto-cycle R003", status="running", started_at_utc=started.isoformat(),
                  python=sys.version, executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, controls_completed=0, unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    log_lines = []

    def log(message):
        log_lines.append(message)
        (run / "runner.stdout.txt").write_text("\n".join(log_lines) + "\n", encoding="utf8")
        print(message)

    controls = []
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        pages = load_pages()
        applicable = [page for page in pages if page["indices"]]
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH),
                      data_versions={"corpus": sha256(CORPUS_PATH), "heldout": sha256(HELDOUT_PATH)},
                      source_files_verified=source_count, code_version=snapshot,
                      page_order=[page["page"] for page in pages],
                      applicable_pages=[page["page"] for page in applicable],
                      excluded_pages=[page["page"] for page in pages if not page["indices"]],
                      rune_count=sum(len(page["indices"]) for page in applicable),
                      lags=list(LAGS), cells=len(applicable) * len(LAGS),
                      statistic="absolute mean chi product within same hard group",
                      control_replicates=CONTROL_REPLICATES, control_seed=CONTROL_SEED,
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE,
                      total_wall_seconds=WALL_SECONDS)
        write_json(run / "frozen.json", frozen)
        record.update(frozen_sha256=sha256(run / "frozen.json"), source_files_verified=source_count)
        write_json(run / "record.json", record)

        sensitivity = synthetic_sensitivity()
        write_json(run / "sensitivity.json", sensitivity)
        if sensitivity["status"] != "passed":
            raise ValueError("Synthetic Legendre sensitivity control failed")
        observed = vector_statistics(applicable)
        independent = manual_statistics(applicable)
        if not np.allclose(observed, independent, rtol=0, atol=0):
            raise ValueError("Vectorized and manual observed statistics differ")
        write_json(run / "observed.json", dict(score_vector=observed,
                                                score_vector_sha256=stable_digest(observed),
                                                manual_replay_sha256=stable_digest(independent)))
        record["observed_cells"] = len(observed)
        record["observed_rune_count"] = sum(len(page["indices"]) for page in applicable)
        write_json(run / "record.json", record)
        log(f"observed cells={len(observed)} runes={record['observed_rune_count']}")

        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() - wall_started > WALL_SECONDS:
                raise TimeoutError(f"H011 wall budget exceeded after {len(controls)} controls")
            replacements = []
            for page in applicable:
                values = list(page["indices"])
                rng.shuffle(values)
                replacements.append(values)
            controls.append(vector_statistics(applicable, replacements))
            record["controls_completed"] = len(controls)
            if replicate % 100 == 0:
                log(f"controls={replicate}")
                write_json(run / "record.json", record)
        matrix = np.asarray(controls, dtype=np.float64)
        npz_path = run / "control-scores.npz"
        np.savez_compressed(npz_path, observed=np.asarray(observed, dtype=np.float64), controls=matrix)
        write_json(run / "control-scores.json", dict(schema=1, completed=len(controls),
                                                     requested=CONTROL_REPLICATES,
                                                     seed=CONTROL_SEED, cells=len(observed),
                                                     npz_path=npz_path.relative_to(ROOT).as_posix(),
                                                     npz_sha256=sha256(npz_path)))
        stats = standardize(observed, controls)
        rows = []
        for index, (page, lag) in enumerate(( (page["page"], lag) for page in applicable for lag in LAGS)):
            p = stats["p_adjusted"][index]
            rows.append(dict(page=page, lag=lag, statistic=observed[index],
                             z=stats["observed_z"][index], p_adjusted=p,
                             status="inconclusive" if p <= ALPHA else "negative"))
        leads = [row for row in rows if row["status"] == "inconclusive"]
        strongest = sorted(rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"], row["lag"]))[:10]
        summary = dict(status="inconclusive" if leads else "negative",
                       verification_status="passed", controls_completed=len(controls),
                       sensitivity=sensitivity,
                       coverage=dict(pages=55, runes=12956, lags=28, cells=len(rows),
                                     control_replicates=len(controls), unsolved_page_candidates=[]),
                       leads=leads, strongest=strongest,
                       standardization=dict(observed_z=stats["observed_z"],
                                            p_adjusted=stats["p_adjusted"],
                                            control_max_z=stats["control_max_z"]),
                       interpretation="Projection lead is diagnostic only; no page is accepted as decrypted.",
                       negative_scope="Only H011 Legendre projection, hard-group lag 1..28 and within-page permutation null.")
        write_json(run / "statistics.json", summary)
        record["status"] = summary["status"]
        record["result"] = dict(leads=len(leads), strongest=strongest[:3], controls_completed=len(controls))
        record["actual_coverage"] = summary["coverage"]
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H011 execution")
        record["reproduction_bundle"] = archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    except Exception as exc:
        record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
        record["error"] = repr(exc)
        record["controls_completed"] = len(controls)
        if controls:
            np.savez_compressed(run / "control-scores.partial.npz", controls=np.asarray(controls, dtype=np.float64))
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
