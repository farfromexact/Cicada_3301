"""Run H017: bounded first-order ciphertext feedback on the LP2 corpus."""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import random
import sys
import time
import traceback
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.execution import execute
from lp_lab.feedback import cumulative_encrypt
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import indices
from lp_lab.synthetic import encode_text


SPEC_PATH = ROOT / "hypotheses/H017-ciphertext-feedback-v1.json"
H009_SPEC_PATH = ROOT / "hypotheses/H009-short-scorer-calibration-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
WORKER_PATH = ROOT / "scripts/attempt14_feedback_worker_v1.py"
HYPOTHESIS = "H017-ciphertext-feedback-v1"
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011701
SYNTHETIC_SEED = 33011702
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25
EXPECTED_POSITIVE_JOB_IDS = frozenset(
    {"synthetic-positive-1", "synthetic-positive-2"}
)

PAGE_FIELDS = ("page", "rune_count", "decoded_indices", "initial_previous_cipher")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )


def stable_digest(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def append_jsonl(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()


def load_pages():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    pages = corpus["pages"]
    expected_ids = [f"LP2/{number}" for number in range(56)]
    if [page["page"] for page in pages] != expected_ids:
        raise ValueError("Corpus page order or universe changed")
    public_pages = []
    metadata = []
    for page in pages:
        raw = page["raw"]
        raw_hash = hashlib.sha256(raw.encode("utf8")).hexdigest()
        if raw_hash != page["raw_sha256"]:
            raise ValueError(f"Corpus raw hash mismatch: {page['page']}")
        if sha256(ROOT / page["source"]) != page["source_sha256"]:
            raise ValueError(f"Corpus source hash mismatch: {page['page']}")
        cipher = indices(raw)
        if len(cipher) != page["rune_count"]:
            raise ValueError(f"Corpus rune count mismatch: {page['page']}")
        metadata.append(
            dict(
                page=page["page"],
                page_number=page["page_number"],
                rune_count=len(cipher),
                raw_sha256=raw_hash,
                source=page["source"],
                source_sha256=page["source_sha256"],
                image_path=page["image_path"],
                image_sha256=page["image_sha256"],
                applicability=page["applicability"],
            )
        )
        if cipher:
            public_pages.append(dict(page=page["page"], cipher=cipher))
    if len(public_pages) != 55:
        raise ValueError("Unexpected number of applicable pages")
    if [page["page"] for page in pages if not page["rune_count"]] != ["LP2/50"]:
        raise ValueError("Unexpected inapplicable page")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("Unexpected rune count")
    return pages, public_pages, metadata


def scorer_basis():
    training = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
    counts = [training.count(value) for value in range(29)]
    total = len(training)
    weights = [math.log((count + 1) / (total + 29)) for count in counts]
    return training, counts, weights


def score(decoded, weights):
    if len(decoded) <= 1:
        return None
    return sum(weights[value] for value in decoded[1:]) / (len(decoded) - 1)


def independent_difference(cipher):
    """Direct neighbor subtraction, deliberately separate from worker import."""
    previous = 0
    decoded = []
    for value in cipher:
        if type(value) is not int or not 0 <= value < 29:
            raise ValueError("Cipher outside rune domain")
        decoded.append((value - previous) % 29)
        previous = value
    return decoded


def independent_job(job):
    rows = []
    for page in job["pages"]:
        decoded = independent_difference(page["cipher"])
        rows.append(
            dict(
                page=page["page"],
                rune_count=len(page["cipher"]),
                decoded_indices=decoded,
                initial_previous_cipher=0,
            )
        )
    return dict(id=job["id"], pages=rows)


def synthetic_controls(heldout):
    if len(heldout) < 256:
        raise ValueError("Heldout text is too short for H017 synthetic controls")
    plans = [list(heldout[:128])]
    plans[0][0] = 0
    plans[0][1] = 0
    plans[0][2] = 1
    plans[0][3] = 28
    rng = random.Random(SYNTHETIC_SEED)
    random_plain = [rng.randrange(29) for _ in range(128)]
    random_plain[0] = 0
    random_plain[1] = 0
    random_plain[2] = 1
    random_plain[3] = 28
    plans.append(random_plain)

    jobs = []
    answers = {}
    for index, plaintext in enumerate(plans, start=1):
        job_id = f"synthetic-positive-{index}"
        cipher = cumulative_encrypt(plaintext)
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        answers[job_id] = dict(
            kind="positive",
            plaintext=plaintext,
            cipher=cipher,
            expected_decoded=plaintext,
        )
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS:
        raise ValueError("Synthetic H017 answer registration drifted")
    return jobs, answers


def make_public_and_answers(public_pages, heldout):
    jobs = [dict(id="unsolved-page-reset", pages=public_pages)]
    synthetic_jobs, answers = synthetic_controls(heldout)
    jobs.extend(synthetic_jobs)
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=jobs), answers


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H017 worker output fields")
    if output["status"] != "completed" or not output["read_guard_probe_passed"]:
        raise ValueError("H017 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output["jobs"]] != public_ids:
        raise ValueError("H017 worker omitted or reordered jobs")
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS:
        raise ValueError("H017 private answer map is incomplete or unexpected")

    expected_positive_checks = []
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job.get("id") != public_job["id"]:
            raise ValueError("H017 worker job identity mismatch")
        expected = independent_job(public_job)
        if len(output_job.get("pages", [])) != len(expected["pages"]):
            raise ValueError(f"H017 page coverage mismatch: {public_job['id']}")
        for actual, expected_row in zip(output_job["pages"], expected["pages"]):
            if any(actual.get(field) != expected_row[field] for field in PAGE_FIELDS):
                raise ValueError(f"Independent H017 transform mismatch: {public_job['id']}/{actual.get('page')}")
        if public_job["id"] in EXPECTED_POSITIVE_JOB_IDS:
            answer = answers[public_job["id"]]
            row = output_job["pages"][0]
            if row["decoded_indices"] != answer["expected_decoded"]:
                raise ValueError(f"H017 synthetic plaintext mismatch: {public_job['id']}")
            if cumulative_encrypt(row["decoded_indices"]) != answer["cipher"]:
                raise ValueError(f"H017 synthetic cumulative roundtrip failed: {public_job['id']}")
            expected_positive_checks.append(
                dict(job=public_job["id"], rune_count=row["rune_count"])
            )

    if {row["job"] for row in expected_positive_checks} != EXPECTED_POSITIVE_JOB_IDS:
        raise ValueError("H017 positive validation is incomplete")
    if len(expected_positive_checks) != len(EXPECTED_POSITIVE_JOB_IDS):
        raise ValueError("H017 positive validation contains duplicate checks")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        public_sha256=stable_digest(public),
        positive_path_checks=expected_positive_checks,
        independent_algorithm="direct neighbor subtraction and cumulative roundtrip",
    )


def standardize(observed, controls):
    if len(observed) != 55 or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected H017 score shape")
    if any(len(row) != len(observed) for row in controls):
        raise ValueError("H017 control score width mismatch")
    values_by_unit = [[observed[index]] + [row[index] for row in controls] for index in range(55)]
    means = []
    stds = []
    for values in values_by_unit:
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(math.sqrt(variance))
    observed_z = [
        (value - mean) / std if std > 0 else 0.0
        for value, mean, std in zip(observed, means, stds)
    ]
    control_max = [
        max(
            (value - mean) / std if std > 0 else 0.0
            for value, mean, std in zip(row, means, stds)
        )
        for row in controls
    ]
    p_values = [
        (1 + sum(max_z >= z - TIE_TOLERANCE for max_z in control_max))
        / (len(control_max) + 1)
        if std > 0
        else 1.0
        for z, std in zip(observed_z, stds)
    ]
    return dict(
        means=means,
        stds=stds,
        observed_z=observed_z,
        control_max_z=control_max,
        p_adjusted=p_values,
    )


def save_checkpoint(path, *, completed, partial_path, frozen, rng, status):
    frozen_value = json.loads(frozen.read_text(encoding="utf8"))
    checkpoint = dict(
        schema=1,
        status=status,
        completed=completed,
        last_replicate=completed,
        requested=CONTROL_REPLICATES,
        unit_count=55,
        seed=CONTROL_SEED,
        partial_path=partial_path.name,
        partial_sha256=sha256(partial_path) if partial_path.exists() else None,
        frozen_sha256=sha256(frozen),
        code_version_digest=frozen_value["code_version"]["digest"],
        public_sha256=frozen_value["public_sha256"],
        rng_state_sha256=stable_digest(rng.getstate()),
        replay_rule="restart from seed and consume exactly one full-page permutation per applicable page per replicate",
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )
    os.replace(temporary, path)


def archive_run(run, snapshot):
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / path for path in snapshot["files"]]
    paths.extend(
        path
        for directory in ("sources", "data", "hypotheses", "research")
        for path in (ROOT / directory).rglob("*")
        if path.is_file()
    )
    paths.extend(path for path in run.rglob("*") if path.is_file() and path != archive)
    knowledge = json.loads((ROOT / "research/knowledge.json").read_text(encoding="utf8"))
    paths.extend(ROOT / entry["artifact"] for entry in knowledge["experiments"])
    paths.extend(ROOT / name for name in ("README.md", "AGENTS.md", "STATE.md"))
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive), bytes=archive.stat().st_size)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Run folder must be inside repository runs")
    run.mkdir(parents=True, exist_ok=False)
    started_at = dt.datetime.now(dt.timezone.utc)
    stopwatch = time.monotonic()
    deadline = stopwatch + WALL_SECONDS
    snapshot = code_snapshot(ROOT)
    record = dict(
        schema=1,
        attempt="auto-cycle R009",
        hypothesis=HYPOTHESIS,
        status="running",
        started_at_utc=started_at.isoformat(),
        python=sys.version,
        executable=sys.executable,
        platform=platform.platform(),
        code_version=snapshot,
        controls_completed=0,
        unsolved_page_candidates=[],
    )
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        if spec.get("id") != HYPOTHESIS or spec.get("status") != "preregistered":
            raise ValueError("H017 specification is not preregistered")
        _, public_pages, metadata = load_pages()
        training, training_counts, weights = scorer_basis()
        heldout = encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))
        public, answers = make_public_and_answers(public_pages, heldout)
        source_paths = [
            SPEC_PATH.relative_to(ROOT).as_posix(),
            H009_SPEC_PATH.relative_to(ROOT).as_posix(),
            CORPUS_PATH.relative_to(ROOT).as_posix(),
            TRAIN_PATH.relative_to(ROOT).as_posix(),
        ]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        page_order = [page["page"] for page in public_pages]
        unit_order = list(page_order)
        write_json(
            run / "inputs.json",
            dict(
                schema=1,
                derived_at_utc=started_at.isoformat(),
                corpus_version="attempt1-corpus-v1",
                pages=metadata,
                public_job_ids=[job["id"] for job in public["jobs"]],
                public_sha256=stable_digest(public),
            ),
        )
        write_json(run / "public.json", public)
        write_json(run / "verifier-only" / "answers.json", answers)
        frozen = run / "frozen.json"
        write_json(
            frozen,
            dict(
                schema=1,
                frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                specification=spec,
                source_hashes=source_hashes,
                code_version=snapshot,
                page_order=page_order,
                applicable_pages=page_order,
                excluded_pages=["LP2/50"],
                rune_count=12956,
                score_units=55,
                score_excludes_first_rune=True,
                training_path=TRAIN_PATH.relative_to(ROOT).as_posix(),
                training_sha256=sha256(TRAIN_PATH),
                training_rune_count=len(training),
                training_counts=training_counts,
                scorer_weights=weights,
                control_replicates=CONTROL_REPLICATES,
                control_seed=CONTROL_SEED,
                synthetic_seed_verifier_only=SYNTHETIC_SEED,
                alpha=ALPHA,
                tie_tolerance=TIE_TOLERANCE,
                total_wall_seconds=WALL_SECONDS,
                checkpoint_every=CHECKPOINT_EVERY,
                expected_positive_job_ids=sorted(EXPECTED_POSITIVE_JOB_IDS),
                expected_answers_sha256=sha256(run / "verifier-only" / "answers.json"),
                public_sha256=stable_digest(public),
            ),
        )
        record.update(
            execution_started=True,
            source_files_verified=source_count,
            frozen_sha256=sha256(frozen),
        )
        write_json(run / "record.json", record)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("H017 deadline expired before worker")
        execution = execute(
            [sys.executable, "-I", "-S", str(WORKER_PATH)],
            cwd=ROOT,
            timeout=remaining,
            stdin=json.dumps(public),
        )
        write_json(run / "worker-execution.json", execution)
        (run / "worker-stdout.json").write_text(execution["stdout"], encoding="utf8")
        (run / "worker-stderr.txt").write_text(execution["stderr"], encoding="utf8")
        if execution["status"] == "timeout":
            raise TimeoutError("H017 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H017 worker failed; see worker-execution.json")
        output = json.loads(execution["stdout"])
        write_json(run / "worker-output.json", output)
        verification = verify_worker(public, output, answers)
        write_json(run / "independent-verification.json", verification)
        observed_output = next(job for job in output["jobs"] if job["id"] == "unsolved-page-reset")
        observed_rows = []
        for row in observed_output["pages"]:
            observed_rows.append(
                dict(
                    page=row["page"],
                    rune_count=row["rune_count"],
                    decoded_indices=row["decoded_indices"],
                    score=score(row["decoded_indices"], weights),
                )
            )
        observed = [row["score"] for row in observed_rows]
        if [row["page"] for row in observed_rows] != page_order:
            raise ValueError("Observed H017 page order changed")
        write_json(
            run / "decoded.json",
            dict(
                algorithm="P[0]=C[0]; P[i]=(C[i]-C[i-1]) mod29",
                score_excludes_first_rune=True,
                pages=observed_rows,
                score_vector=observed,
                score_vector_sha256=stable_digest(observed),
            ),
        )

        controls = []
        partial_path = run / "control-scores.partial.jsonl"
        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"H017 wall budget exceeded after {len(controls)} controls")
            shuffled_pages = []
            for page in public_pages:
                cipher = list(page["cipher"])
                rng.shuffle(cipher)
                shuffled_pages.append(dict(page=page["page"], cipher=cipher))
            control_output = independent_job(dict(id="control", pages=shuffled_pages))
            metrics = [score(row["decoded_indices"], weights) for row in control_output["pages"]]
            if any(value is None or not math.isfinite(value) for value in metrics):
                raise ValueError("Non-finite H017 control score")
            controls.append(metrics)
            append_jsonl(
                partial_path,
                dict(
                    replicate=replicate,
                    metrics=metrics,
                    metrics_sha256=stable_digest(metrics),
                    rng_state_sha256=stable_digest(rng.getstate()),
                ),
            )
            record["controls_completed"] = replicate
            if replicate % CHECKPOINT_EVERY == 0 or replicate == CONTROL_REPLICATES:
                save_checkpoint(
                    run / "control-checkpoint.json",
                    completed=replicate,
                    partial_path=partial_path,
                    frozen=frozen,
                    rng=rng,
                    status="complete" if replicate == CONTROL_REPLICATES else "partial",
                )
                write_json(run / "record.json", record)
        if time.monotonic() >= deadline:
            raise TimeoutError("H017 wall budget exceeded after final control")
        write_json(
            run / "control-scores.json",
            dict(
                schema=1,
                algorithm="within-page full ciphertext permutation",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=unit_order,
                score_rows=controls,
            ),
        )
        stats = standardize(observed, controls)
        stat_rows = []
        for page, metric, z, p, std in zip(
            page_order,
            observed,
            stats["observed_z"],
            stats["p_adjusted"],
            stats["stds"],
        ):
            statistic_status = "zero_variance" if std == 0 else (
                "lead" if p <= ALPHA else "not_detected"
            )
            stat_rows.append(
                dict(
                    page=page,
                    score=metric,
                    statistic_status=statistic_status,
                    candidate=statistic_status == "lead",
                    z=z,
                    p_adjusted=p,
                )
            )
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"]))[:10]
        summary = dict(
            status="inconclusive" if leads else "negative",
            hypothesis=HYPOTHESIS,
            verification_status="passed",
            controls_completed=len(controls),
            coverage=dict(
                pages=55,
                applicable_pages=55,
                excluded_pages=["LP2/50"],
                runes=12956,
                score_units=55,
                control_replicates=len(controls),
                unsolved_page_candidates=[row["page"] for row in leads],
            ),
            leads=leads,
            strongest=strongest,
            statistic_rows=stat_rows,
            statistics=stats,
            interpretation=(
                "The first-difference output is a deterministic compatibility measurement; "
                "no language completion or output-selected plaintext was used."
            ),
            negative_scope=(
                "Only H017's page-reset C[-1]=0 first-difference transform, first-rune-excluded "
                "training-only unigram score and full within-page permutation null."
            ),
            limitation=(
                "No independent LP2 plaintext or image-level glyph audit is available; LP2/50 literal grid is unexecuted."
            ),
        )
        write_json(run / "statistics.json", summary)
        record.update(
            status=summary["status"],
            result=dict(leads=len(leads), strongest=strongest[:3]),
            actual_coverage=summary["coverage"],
            unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"],
        )
        if code_snapshot(ROOT) != snapshot or any(
            sha256(ROOT / path) != value for path, value in source_hashes.items()
        ):
            raise ValueError("Frozen H017 code or source input changed during execution")
        verify_sources(ROOT)
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc))
        (run / "exception.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    record.update(
        finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic() - stopwatch,
    )
    write_json(run / "record.json", record)
    try:
        record["reproduction_bundle"] = archive_run(run, snapshot)
    except Exception as exc:
        record.update(status="error", error=f"ArchiveError: {exc!r}")
        (run / "archive-exception.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    write_json(run / "record.json", record)
    print(
        json.dumps(
            {
                "run": run.relative_to(ROOT).as_posix(),
                "status": record["status"],
                "controls_completed": record.get("controls_completed"),
                "unsolved_page_candidates": record.get("unsolved_page_candidates"),
                "elapsed_seconds": record.get("elapsed_seconds"),
                "error": record.get("error"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
