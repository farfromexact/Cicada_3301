"""Run H018: x^4 projection power gate followed by the LP2 diagnostic."""

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
from lp_lab.projection import SUBGROUP
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import indices


SPEC_PATH = ROOT / "hypotheses/H018-fourth-power-projection-v1.json"
H011_SPEC_PATH = ROOT / "hypotheses/H011-legendre-projection-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
WORKER_PATH = ROOT / "scripts/attempt15_projection_worker_v1.py"
HYPOTHESIS = "H018-fourth-power-projection-v1"
GATE_POSITIVE_COUNT = 20
GATE_NEGATIVE_COUNT = 20
GATE_LENGTH = 128
GATE_THRESHOLD = 0.75
GATE_POSITIVE_SEED = 33011801
GATE_MULTIPLIER_SEED = 33011802
GATE_NEGATIVE_SEED = 33011803
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011804
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25
PAGE_FIELDS = ("page", "rune_count", "projected_indices")


class GateFailure(RuntimeError):
    """A failed synthetic gate makes the LP2 portion scientifically invalid."""


SOURCE_REVIEW_PATH = ROOT / "reviews/feed009-29-group-ideas.md"


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
    return public_pages, metadata


PROJECTED_CLASSES = tuple(sorted({pow(value, 4, 29) for value in range(29)}))
PREIMAGES = {
    projected: tuple(value for value in range(29) if pow(value, 4, 29) == projected)
    for projected in PROJECTED_CLASSES
}


def repeated_fourth(value):
    if type(value) is not int or not 0 <= value < 29:
        raise ValueError("Projection input outside rune domain")
    square = (value * value) % 29
    return (square * square) % 29


def independent_projection(values):
    return [repeated_fourth(value) for value in values]


def projection_score(values):
    if len(values) <= 1:
        return None
    projected = independent_projection(values)
    return sum(
        projected[index] == projected[index - 1] for index in range(1, len(projected))
    ) / (len(projected) - 1)


def make_run_pattern(index):
    return [PROJECTED_CLASSES[((position // 8) + index) % len(PROJECTED_CLASSES)] for position in range(GATE_LENGTH)]


def lift_projection(projected):
    return [PREIMAGES[value][0] for value in projected]


def subgroup_encrypt(plaintext, rng):
    multipliers = [SUBGROUP[rng.randrange(len(SUBGROUP))] for _ in plaintext]
    cipher = [(multiplier * value) % 29 for multiplier, value in zip(multipliers, plaintext)]
    return cipher, multipliers


def synthetic_gate():
    multiplier_rng = random.Random(GATE_MULTIPLIER_SEED)
    negative_rng = random.Random(GATE_NEGATIVE_SEED)
    jobs = []
    answers = {}
    labels = {}
    for index in range(1, GATE_POSITIVE_COUNT + 1):
        expected = make_run_pattern(index)
        plaintext = lift_projection(expected)
        cipher, multipliers = subgroup_encrypt(plaintext, multiplier_rng)
        job_id = f"gate-positive-{index:02d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        answers[job_id] = dict(
            kind="positive",
            plaintext=plaintext,
            projected=expected,
            cipher=cipher,
            multipliers=multipliers,
        )
        labels[job_id] = "positive"
    for index in range(1, GATE_NEGATIVE_COUNT + 1):
        expected = make_run_pattern(index)
        negative = randomize_preserving_zero_positions(expected, negative_rng)
        plaintext = lift_projection(negative)
        cipher, multipliers = subgroup_encrypt(plaintext, multiplier_rng)
        job_id = f"gate-negative-{index:02d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        answers[job_id] = dict(
            kind="negative",
            plaintext=plaintext,
            projected=negative,
            cipher=cipher,
            multipliers=multipliers,
        )
        labels[job_id] = "negative"
    if len(jobs) != GATE_POSITIVE_COUNT + GATE_NEGATIVE_COUNT:
        raise ValueError("H018 gate job count drifted")
    return jobs, answers, labels


def build_public(public_pages):
    gate_jobs, answers, labels = synthetic_gate()
    gate_jobs.append(dict(id="unsolved-page-reset", pages=public_pages))
    labels["unsolved-page-reset"] = "lp2"
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=gate_jobs), answers, labels


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H018 worker output fields")
    if output["status"] != "completed" or not output["read_guard_probe_passed"]:
        raise ValueError("H018 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output["jobs"]] != public_ids:
        raise ValueError("H018 worker omitted or reordered jobs")
    positive_ids = {
        job_id for job_id, answer in answers.items() if answer["kind"] == "positive"
    }
    negative_ids = {
        job_id for job_id, answer in answers.items() if answer["kind"] == "negative"
    }
    if len(positive_ids) != GATE_POSITIVE_COUNT or len(negative_ids) != GATE_NEGATIVE_COUNT:
        raise ValueError("H018 gate answer counts drifted")

    positive_checks = []
    page_checks = 0
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job.get("id") != public_job["id"]:
            raise ValueError("H018 worker job identity mismatch")
        expected_job = dict(id=public_job["id"], pages=public_job["pages"])
        expected_rows = []
        for page in expected_job["pages"]:
            expected_rows.append(
                dict(
                    page=page["page"],
                    rune_count=len(page["cipher"]),
                    projected_indices=independent_projection(page["cipher"]),
                )
            )
        if len(output_job.get("pages", [])) != len(expected_rows):
            raise ValueError(f"H018 page coverage mismatch: {public_job['id']}")
        for actual, expected in zip(output_job["pages"], expected_rows):
            if any(actual.get(field) != expected[field] for field in PAGE_FIELDS):
                raise ValueError(f"Independent H018 projection mismatch: {public_job['id']}/{actual.get('page')}")
            page_checks += 1
        if public_job["id"] in positive_ids:
            answer = answers[public_job["id"]]
            if output_job["pages"][0]["projected_indices"] != answer["projected"]:
                raise ValueError(f"H018 positive invariant mismatch: {public_job['id']}")
            positive_checks.append(
                dict(job=public_job["id"], rune_count=len(answer["plaintext"]))
            )
        elif public_job["id"] in negative_ids:
            # The negative class is intentionally not given a private expected
            # plaintext check; its role is the fixed-order power gate below.
            if len(output_job["pages"]) != 1:
                raise ValueError(f"H018 negative gate page mismatch: {public_job['id']}")

    invariant_checks = 0
    for multiplier in SUBGROUP:
        for value in range(29):
            if repeated_fourth((multiplier * value) % 29) != repeated_fourth(value):
                raise ValueError("H018 subgroup invariant failed")
            invariant_checks += 1
    if {row["job"] for row in positive_checks} != positive_ids or len(positive_checks) != GATE_POSITIVE_COUNT:
        raise ValueError("H018 positive gate validation is incomplete")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        public_sha256=stable_digest(public),
        positive_projection_checks=positive_checks,
        subgroup_invariant_checks=invariant_checks,
        page_checks=page_checks,
        independent_algorithm="repeated modular multiplication x^2 then x^4, separate from worker helper",
    )


def gate_result(output, answers):
    output_map = {job["id"]: job for job in output["jobs"]}
    positive_scores = []
    negative_scores = []
    positive_exact = 0
    for job_id, answer in answers.items():
        row = output_map[job_id]["pages"][0]
        projected = row["projected_indices"]
        score = sum(projected[index] == projected[index - 1] for index in range(1, len(projected))) / (len(projected) - 1)
        if answer["kind"] == "positive":
            if projected == answer["projected"]:
                positive_exact += 1
            positive_scores.append(dict(job=job_id, score=score, exact=projected == answer["projected"]))
        else:
            negative_scores.append(dict(job=job_id, score=score, false_accept=score >= GATE_THRESHOLD))
    positive_passes = sum(item["exact"] and item["score"] >= GATE_THRESHOLD for item in positive_scores)
    negative_false_accepts = sum(item["false_accept"] for item in negative_scores)
    return dict(
        status="passed" if positive_passes >= 18 and negative_false_accepts == 0 else "failed",
        positive_requested=GATE_POSITIVE_COUNT,
        positive_exact=positive_exact,
        positive_score_passes=positive_passes,
        negative_requested=GATE_NEGATIVE_COUNT,
        negative_false_accepts=negative_false_accepts,
        threshold=GATE_THRESHOLD,
        positive_scores=positive_scores,
        negative_scores=negative_scores,
    )


def gate_allows_lp2(gate):
    return gate.get("status") == "passed"


def build_gate_failure_summary(gate, verification_status):
    return dict(
        status="inconclusive",
        hypothesis=HYPOTHESIS,
        verification_status=verification_status,
        lp2_status="not_run_gate_failed",
        power_gate=gate,
        controls_completed=0,
        coverage=dict(
            pages=0,
            applicable_pages=0,
            requested_pages=55,
            excluded_pages=["LP2/50"],
            runes=0,
            requested_runes=12956,
            score_units=0,
            requested_score_units=55,
            control_replicates=0,
            requested_control_replicates=CONTROL_REPLICATES,
            unsolved_page_candidates=[],
        ),
        leads=[],
        strongest=[],
        statistic_rows=[],
        statistics=None,
        interpretation="The synthetic measurement gate failed; LP2 was not interpreted.",
        negative_scope="No LP2 negative conclusion is valid when the fixed power gate fails.",
        limitation="The gate failure is retained for audit; the LP2 batch must be rerun only under a new frozen version.",
    )


def randomize_preserving_zero_positions(values, rng):
    nonzero = [value for value in values if value != 0]
    rng.shuffle(nonzero)
    result = []
    cursor = 0
    for value in values:
        if value == 0:
            result.append(0)
        else:
            result.append(nonzero[cursor])
            cursor += 1
    if cursor != len(nonzero):
        raise ValueError("H018 zero-preserving shuffle did not consume its multiset")
    return result


def standardize(observed, controls):
    if len(observed) != 55 or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected H018 score shape")
    if any(len(row) != len(observed) for row in controls):
        raise ValueError("H018 control score width mismatch")
    values_by_unit = [[observed[index]] + [row[index] for row in controls] for index in range(55)]
    means = []
    stds = []
    for values in values_by_unit:
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(math.sqrt(variance))
    observed_z = [(value - mean) / std if std > 0 else 0.0 for value, mean, std in zip(observed, means, stds)]
    control_max = [
        max((value - mean) / std if std > 0 else 0.0 for value, mean, std in zip(row, means, stds))
        for row in controls
    ]
    p_values = [
        (1 + sum(max_z >= z - TIE_TOLERANCE for max_z in control_max)) / (len(control_max) + 1)
        if std > 0 else 1.0
        for z, std in zip(observed_z, stds)
    ]
    return dict(means=means, stds=stds, observed_z=observed_z, control_max_z=control_max, p_adjusted=p_values)


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
        replay_rule="restart from seed and consume exactly one zero-preserving page shuffle per applicable page per replicate",
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
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
    paths.extend(
        ROOT / name
        for name in (
            "README.md",
            "AGENTS.md",
            "STATE.md",
            "reviews/feed009-29-group-ideas.md",
        )
    )
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
        attempt="auto-cycle R010",
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
            raise ValueError("H018 specification is not preregistered")
        public_pages, metadata = load_pages()
        public, answers, labels = build_public(public_pages)
        source_paths = [
            SPEC_PATH.relative_to(ROOT).as_posix(),
            H011_SPEC_PATH.relative_to(ROOT).as_posix(),
            CORPUS_PATH.relative_to(ROOT).as_posix(),
            SOURCE_REVIEW_PATH.relative_to(ROOT).as_posix(),
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
                job_labels=labels,
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
                projected_classes=list(PROJECTED_CLASSES),
                subgroup=list(SUBGROUP),
                page_order=page_order,
                applicable_pages=page_order,
                excluded_pages=["LP2/50"],
                rune_count=12956,
                score_units=55,
                gate=dict(
                    positive_count=GATE_POSITIVE_COUNT,
                    negative_count=GATE_NEGATIVE_COUNT,
                    length=GATE_LENGTH,
                    threshold=GATE_THRESHOLD,
                    positive_seed=GATE_POSITIVE_SEED,
                    multiplier_seed=GATE_MULTIPLIER_SEED,
                    negative_seed=GATE_NEGATIVE_SEED,
                ),
                control_replicates=CONTROL_REPLICATES,
                control_seed=CONTROL_SEED,
                alpha=ALPHA,
                tie_tolerance=TIE_TOLERANCE,
                total_wall_seconds=WALL_SECONDS,
                checkpoint_every=CHECKPOINT_EVERY,
                expected_positive_job_ids=sorted(job_id for job_id in answers if answers[job_id]["kind"] == "positive"),
                expected_answers_sha256=sha256(run / "verifier-only" / "answers.json"),
                public_sha256=stable_digest(public),
            ),
        )
        record.update(execution_started=True, source_files_verified=source_count, frozen_sha256=sha256(frozen))
        write_json(run / "record.json", record)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("H018 deadline expired before worker")
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
            raise TimeoutError("H018 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H018 worker failed; see worker-execution.json")
        output = json.loads(execution["stdout"])
        write_json(run / "worker-output.json", output)
        verification = verify_worker(public, output, answers)
        write_json(run / "independent-verification.json", verification)
        gate = gate_result(output, answers)
        write_json(run / "power-gate.json", gate)

        if not gate_allows_lp2(gate):
            if time.monotonic() >= deadline:
                raise TimeoutError("H018 wall budget exceeded after failed power gate")
            summary = build_gate_failure_summary(gate, verification["status"])
            write_json(run / "statistics.json", summary)
            write_json(
                run / "lp2-skipped.json",
                dict(
                    status="skipped",
                    reason="power_gate_failed",
                    power_gate_sha256=sha256(run / "power-gate.json"),
                    requested_pages=55,
                    requested_runes=12956,
                    controls_not_started=True,
                ),
            )
            record.update(
                status="inconclusive",
                result=dict(gate_status=gate["status"], lp2_scanned=False),
                actual_coverage=summary["coverage"],
                unsolved_page_candidates=[],
            )
            raise GateFailure("H018 power gate failed; LP2 scan was not interpreted")

        unsolved = next(job for job in output["jobs"] if job["id"] == "unsolved-page-reset")
        observed_rows = []
        for row in unsolved["pages"]:
            observed_rows.append(
                dict(
                    page=row["page"],
                    rune_count=row["rune_count"],
                    projected_indices=row["projected_indices"],
                    score=projection_score(row["projected_indices"]),
                )
            )
        observed = [row["score"] for row in observed_rows]
        if [row["page"] for row in observed_rows] != page_order:
            raise ValueError("Observed H018 page order changed")
        write_json(
            run / "observed.json",
            dict(
                algorithm="V(x)=x^4 mod29; adjacent equality over projected sequence",
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
                raise TimeoutError(f"H018 wall budget exceeded after {len(controls)} controls")
            shuffled_pages = []
            for page in public_pages:
                shuffled_pages.append(
                    dict(
                        page=page["page"],
                        cipher=randomize_preserving_zero_positions(page["cipher"], rng),
                    )
                )
            metrics = [projection_score(page["cipher"],) for page in shuffled_pages]
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
            raise TimeoutError("H018 wall budget exceeded after final control")
        write_json(
            run / "control-scores.json",
            dict(
                schema=1,
                algorithm="fixed-zero-mask within-page nonzero permutation",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=unit_order,
                score_rows=controls,
            ),
        )
        stats = standardize(observed, controls)
        stat_rows = []
        for page, metric, z, p, std in zip(page_order, observed, stats["observed_z"], stats["p_adjusted"], stats["stds"]):
            statistic_status = "zero_variance" if std == 0 else ("lead" if p <= ALPHA else "not_detected")
            stat_rows.append(
                dict(page=page, score=metric, statistic_status=statistic_status, candidate=statistic_status == "lead", z=z, p_adjusted=p)
            )
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"]))[:10]
        summary_status = "inconclusive" if gate["status"] != "passed" or leads else "negative"
        summary = dict(
            status=summary_status,
            hypothesis=HYPOTHESIS,
            verification_status="passed",
            power_gate=gate,
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
                "V is a necessary-condition projection diagnostic. It does not identify arbitrary multipliers "
                "or recover plaintext; no language completion or output-selected transform was used."
            ),
            negative_scope=(
                "Only H018's V=x^4 projection, adjacent projected-class equality, zero-preserving permutation null "
                "and the completed synthetic power gate."
            ),
            limitation=(
                "No independent LP2 plaintext or image-level glyph audit is available; LP2/50 literal grid is unexecuted."
            ),
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("H018 wall budget exceeded before statistics finalization")
        write_json(run / "statistics.json", summary)
        if time.monotonic() >= deadline:
            summary["status"] = "timeout"
            summary["scientific_result_valid"] = False
            summary["limitation"] += " Final statistics write crossed the monotonic deadline."
            write_json(run / "statistics.json", summary)
            raise TimeoutError("H018 wall budget exceeded during statistics finalization")
        record.update(
            status=summary["status"],
            result=dict(leads=len(leads), gate_status=gate["status"], strongest=strongest[:3]),
            actual_coverage=summary["coverage"],
            unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"],
        )
        if code_snapshot(ROOT) != snapshot or any(sha256(ROOT / path) != value for path, value in source_hashes.items()):
            raise ValueError("Frozen H018 code or source input changed during execution")
        verify_sources(ROOT)
    except Exception as exc:
        if isinstance(exc, GateFailure):
            record.update(status="inconclusive", gate_failure=str(exc))
        else:
            record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc))
            (run / "exception.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    record.update(finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - stopwatch)
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
