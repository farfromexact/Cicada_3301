"""Run the bounded H009 short-text scorer calibration.

The worker is the existing isolated search_worker.py.  This runner owns all
private answers, deterministic case generation, independent arithmetic
replay, and append-only evidence.  It never sends heldout text or seeds to the
worker.
"""
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
from lp_lab.execution import execute
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.synthetic import encode_text, generate

SPEC_PATH = ROOT / "hypotheses/H009-short-scorer-calibration-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
HELDOUT_PATH = ROOT / "data/synthetic/heldout.txt"
CASE_LENGTH = 256
CALIBRATION_POSITIVES = 8
CALIBRATION_NEGATIVES = 8
EVALUATION_POSITIVES = 20
EVALUATION_NEGATIVES = 20
WORKER_CANDIDATES = 928
SEEDS = {
    "case_plan": 33010900,
    "positive_calibration": 33010901,
    "positive_evaluation": 33010902,
    "negative_calibration": 33010903,
    "negative_evaluation": 33010904,
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def independent_primes(count):
    if type(count) is not int or count < 1:
        raise ValueError("Prime count must be positive")
    bound = max(128, count * 20)
    sieve = bytearray(b"\x01") * (bound + 1)
    sieve[:2] = b"\x00\x00"
    for n in range(2, math.isqrt(bound) + 1):
        if sieve[n]:
            sieve[n * n:bound + 1:n] = b"\x00" * (((bound - n * n) // n) + 1)
    primes = [n for n, flag in enumerate(sieve) if flag]
    if len(primes) < count:
        raise ValueError("Independent sieve bound was insufficient")
    return primes[:count]


def weights_from_counts(counts):
    if len(counts) != 29 or any(type(c) is not int or c < 0 for c in counts):
        raise ValueError("Expected 29 nonnegative training counts")
    total = sum(counts)
    return [math.log((c + 1) / (total + 29)) for c in counts]


def expected_worker(cipher, counts):
    """Independent replay of search_worker.py, without importing it."""
    if len(cipher) != CASE_LENGTH or any(type(c) is not int or not 0 <= c < 29 for c in cipher):
        raise ValueError("Invalid public cipher")
    weights = weights_from_counts(counts)
    primes = independent_primes(len(cipher) + 31)
    rankings = []
    for offset in range(32):
        for shift in range(29):
            plain = [(c - primes[i + offset] + shift) % 29 for i, c in enumerate(cipher)]
            score = sum(weights[p] for p in plain)
            rankings.append({"offset": offset, "shift": shift, "score": score,
                             "plaintext": plain})
    rankings.sort(key=lambda row: (-row["score"], row["offset"], row["shift"]))
    best = rankings[0]
    return dict(selected={k: best[k] for k in ("offset", "shift", "score")},
                plaintext=best["plaintext"],
                score_gap=best["score"] - rankings[1]["score"],
                rankings=rankings)


def public_case(cipher, counts):
    return dict(schema=1, ciphertext=cipher, training_counts=counts,
                offset_max=31, shift_max=28)


def make_plan(heldout_length):
    valid = heldout_length - CASE_LENGTH + 1
    if valid < CALIBRATION_POSITIVES + EVALUATION_POSITIVES:
        raise ValueError("Heldout corpus cannot provide the frozen case offsets")
    starts = random.Random(SEEDS["case_plan"]).sample(range(valid),
                                                       CALIBRATION_POSITIVES + EVALUATION_POSITIVES)

    def seeds_for(name, count):
        rng = random.Random(SEEDS[name])
        return [rng.getrandbits(128) for _ in range(count)]

    plans = []
    for phase, count, offset in (("calibration", CALIBRATION_POSITIVES, 0),
                                 ("evaluation", EVALUATION_POSITIVES, CALIBRATION_POSITIVES)):
        for i, seed in enumerate(seeds_for("positive_" + phase, count)):
            plans.append(dict(id=f"{phase}-positive-{i:02d}", phase=phase,
                              kind="positive", start=starts[offset + i], seed=seed))
        for i, seed in enumerate(seeds_for("negative_" + phase,
                                           CALIBRATION_NEGATIVES if phase == "calibration" else EVALUATION_NEGATIVES)):
            plans.append(dict(id=f"{phase}-random-{i:02d}", phase=phase,
                              kind="random_control", start=None, seed=seed))
    return plans


def generate_case(plan, heldout, counts):
    folder_seed = plan["seed"]
    if plan["kind"] == "positive":
        plain = heldout[plan["start"]:plan["start"] + CASE_LENGTH]
        cipher, answer = generate(plain, folder_seed)
        private = dict(id=plan["id"], kind=plan["kind"], seed=folder_seed,
                       start=plan["start"], key=answer["key"], plaintext=plain)
    else:
        rng = random.Random(folder_seed)
        cipher = [rng.randrange(29) for _ in range(CASE_LENGTH)]
        private = dict(id=plan["id"], kind=plan["kind"], seed=folder_seed,
                       plaintext=None, key=None)
    return cipher, private, public_case(cipher, counts)


def run_worker(case_folder, public):
    write_json(case_folder / "public.json", public)
    execution = execute([sys.executable, "-I", "-S", "-X", "utf8",
                         str(ROOT / "scripts/search_worker.py")],
                        cwd=case_folder, timeout=20,
                        stdin=json.dumps(public, ensure_ascii=False))
    write_json(case_folder / "execution.json", execution)
    (case_folder / "stdout.json").write_text(execution["stdout"], encoding="utf8")
    (case_folder / "stderr.txt").write_text(execution["stderr"], encoding="utf8")
    if execution["status"] != "completed":
        raise RuntimeError(f"worker {execution['status']}: {case_folder.name}")
    try:
        answer = json.loads(execution["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"worker emitted invalid JSON: {case_folder.name}") from exc
    if not answer.get("read_guard_probe_passed"):
        raise RuntimeError(f"worker read isolation failed: {case_folder.name}")
    return answer, execution


def validate_worker(public, worker, private, counts):
    replay = expected_worker(public["ciphertext"], counts)
    if worker.get("covered") != WORKER_CANDIDATES:
        raise ValueError("Worker candidate coverage is not exactly 928")
    if len(worker.get("rankings", [])) != WORKER_CANDIDATES:
        raise ValueError("Worker did not return all fixed rankings")
    if worker.get("selected") != replay["selected"]:
        raise ValueError("Independent best-candidate replay disagrees")
    if worker.get("plaintext") != replay["plaintext"]:
        raise ValueError("Independent plaintext replay disagrees")
    if not math.isclose(worker.get("score_gap"), replay["score_gap"],
                        rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Independent score-gap replay disagrees")
    if private["kind"] == "positive":
        key = private["key"]
        exact_key = worker["selected"]["offset"] == key["offset"] and worker["selected"]["shift"] == key["shift"]
        exact_plaintext = worker["plaintext"] == private["plaintext"]
        primes = independent_primes(CASE_LENGTH + key["offset"])
        reencrypted = [(p + primes[i + key["offset"]] - key["shift"]) % 29
                       for i, p in enumerate(private["plaintext"])]
        roundtrip = reencrypted == public["ciphertext"]
    else:
        exact_key = False
        exact_plaintext = False
        roundtrip = None
    return dict(exact_key=exact_key, exact_plaintext=exact_plaintext,
                roundtrip=roundtrip, selected=worker["selected"],
                score=float(worker["selected"]["score"]),
                score_gap=float(worker["score_gap"]),
                covered=worker["covered"],
                read_guard_probe_passed=worker["read_guard_probe_passed"])


def archive_run(run, snapshot):
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / p for p in snapshot["files"]]
    paths.extend(p for directory in ("data", "sources", "hypotheses", "research")
                 for p in (ROOT / directory).rglob("*") if p.is_file())
    paths.extend(p for p in run.rglob("*") if p.is_file() and p != archive)
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
    record = dict(schema=1, hypothesis="H009-short-scorer-calibration-v1",
                  attempt="auto-cycle R001", status="running",
                  started_at_utc=started.isoformat(), python=sys.version,
                  executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, commands=[], cases_completed=0,
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    log_lines = []

    def log(message):
        log_lines.append(message)
        (run / "runner.stdout.txt").write_text("\n".join(log_lines) + "\n", encoding="utf8")
        print(message)

    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        train = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
        heldout = encode_text(HELDOUT_PATH.read_text(encoding="utf8"))
        counts = [train.count(i) for i in range(29)]
        plans = make_plan(len(heldout))
        frozen = dict(
            schema=1,
            frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            hypothesis_sha256=sha256(SPEC_PATH),
            data_versions={"training": sha256(TRAIN_PATH), "heldout": sha256(HELDOUT_PATH)},
            source_files_verified=source_count,
            code_version=snapshot,
            training_rune_count=len(train),
            training_counts=counts,
            scorer_weights=weights_from_counts(counts),
            case_length=CASE_LENGTH,
            worker_candidates=WORKER_CANDIDATES,
            calibration=dict(positives=CALIBRATION_POSITIVES, random_controls=CALIBRATION_NEGATIVES),
            evaluation=dict(positives=EVALUATION_POSITIVES, random_controls=EVALUATION_NEGATIVES),
            plans=plans,
            acceptance_rule=spec["scorer_and_acceptance_version"],
            random_seeds=SEEDS,
            heldout_sampling_note="Distinct fixed start offsets in one heldout source; keys/controls are independent, but the 28 text windows overlap and are not 28 independent corpora.",
            total_wall_seconds=spec["total_budget"]["wall_seconds"],
        )
        write_json(run / "frozen.json", frozen)
        record["frozen_sha256"] = sha256(run / "frozen.json")
        record["source_files_verified"] = source_count
        write_json(run / "record.json", record)
        by_id = {plan["id"]: plan for plan in plans}
        phase_results = {"calibration": [], "evaluation": []}
        for phase in ("calibration", "evaluation"):
            if phase == "calibration":
                threshold = float("-inf")
            else:
                calibration = phase_results["calibration"]
                pos_scores = [row["score"] for row in calibration if row["kind"] == "positive"]
                neg_scores = [row["score"] for row in calibration if row["kind"] == "random_control"]
                min_positive = min(pos_scores)
                max_negative = max(neg_scores)
                threshold = ((min_positive + max_negative) / 2
                             if min_positive > max_negative else min_positive)
                calibration_record = dict(min_positive_score=min_positive,
                                          max_random_score=max_negative,
                                          threshold=threshold,
                                          separated=min_positive > max_negative,
                                          rule="midpoint when separated, otherwise min positive score")
                write_json(run / "calibration.json", calibration_record)
                record["calibration"] = calibration_record
                write_json(run / "record.json", record)
                log(f"calibration threshold={threshold:.12f} separated={calibration_record['separated']}")
            for plan in plans:
                if plan["phase"] != phase:
                    continue
                cipher, private, public = generate_case(plan, heldout, counts)
                folder = run / "cases" / plan["id"]
                folder.mkdir(parents=True, exist_ok=False)
                write_json(folder / "verifier-only/answer.json", private)
                worker, execution = run_worker(folder, public)
                validation = validate_worker(public, worker, private, counts)
                row = dict(id=plan["id"], phase=phase, kind=plan["kind"],
                           start=plan["start"], seed=plan["seed"],
                           status="passed" if execution["status"] == "completed" else execution["status"],
                           **validation)
                row["accepted"] = (None if phase == "calibration" else row["score"] > threshold)
                row["case_status"] = ("calibration_only" if phase == "calibration" else
                                       "true_recovery" if plan["kind"] == "positive" and
                                       row["accepted"] and row["exact_key"] and
                                       row["exact_plaintext"] and row["roundtrip"]
                                       else "false_accept" if plan["kind"] == "random_control" and row["accepted"]
                                       else "rejected_or_wrong" if plan["kind"] == "random_control"
                                       else "not_recovered")
                write_json(folder / "verification.json", row)
                phase_results[phase].append(row)
                record["cases_completed"] += 1
                record["commands"].append(dict(case=plan["id"], **{
                    k: execution[k] for k in ("status", "exit_code", "elapsed_seconds")
                }))
                write_json(run / "record.json", record)
                log(f"{plan['id']} {row['case_status']} score={row['score']:.6f}")
                if time.monotonic() - wall_started > 120:
                    raise TimeoutError("H009 wall budget exceeded")

        positives = [r for r in phase_results["evaluation"] if r["kind"] == "positive"]
        controls = [r for r in phase_results["evaluation"] if r["kind"] == "random_control"]
        threshold = json.loads((run / "calibration.json").read_text(encoding="utf8"))["threshold"]
        summary = dict(
            status="passed" if sum(r["case_status"] == "true_recovery" for r in positives) >= 18 and
                    sum(r["case_status"] == "false_accept" for r in controls) <= 1 else "negative",
            calibration=json.loads((run / "calibration.json").read_text(encoding="utf8")),
            evaluation=dict(positive_cases=len(positives), random_control_cases=len(controls),
                            exact_key_count=sum(r["exact_key"] for r in positives),
                            exact_plaintext_count=sum(r["exact_plaintext"] for r in positives),
                            accepted_positive_count=sum(r["accepted"] for r in positives),
                            true_recovery_count=sum(r["case_status"] == "true_recovery" for r in positives),
                            false_accept_count=sum(r["case_status"] == "false_accept" for r in controls),
                            rejected_random_control_count=sum(r["case_status"] == "rejected_or_wrong" for r in controls),
                            threshold=threshold),
            calibration_cases=phase_results["calibration"],
            evaluation_cases=phase_results["evaluation"],
            coverage=dict(calibration_cases=len(phase_results["calibration"]),
                          evaluation_cases=len(phase_results["evaluation"]),
                          worker_candidates_per_case=WORKER_CANDIDATES,
                          candidate_evaluations=(len(phase_results["calibration"]) + len(phase_results["evaluation"])) * WORKER_CANDIDATES,
                          unsolved_page_candidates=[]),
            interpretation="Tool calibration only; passed does not solve an LP page. Negative is limited to this scorer, case construction and fixed 928-candidate family.",
            limitation=frozen["heldout_sampling_note"],
        )
        write_json(run / "summary.json", summary)
        record["status"] = summary["status"]
        record["result"] = summary["evaluation"]
        record["actual_coverage"] = summary["coverage"]
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during H009 execution")
        record["reproduction_bundle"] = archive_run(run, snapshot)
    except Exception as exc:
        record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
        record["error"] = repr(exc)
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
        log(f"{record['status']}: {record['error']}")
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - wall_started
    write_json(run / "record.json", record)
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(),
                      "status": record["status"],
                      "cases_completed": record.get("cases_completed"),
                      "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
