"""Run R011/H021: a fixed slash-row common-ordinal geometry diagnostic."""

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
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES, indices


SPEC_PATH = ROOT / "hypotheses/H021-row-alignment-geometry-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
DATA_README_PATH = ROOT / "data/README.md"
FEED_SPEC_PATH = ROOT / "hypotheses/FEED010-geometry-audit-v1.json"
FEED_REVIEW_PATH = ROOT / "reviews/feed010-operational-metaphors.md"
H008_REVIEW_PATH = ROOT / "reviews/attempt-004.md"
WORKER_PATH = ROOT / "scripts/attempt16_row_geometry_worker_v1.py"
HYPOTHESIS = "H021-row-alignment-geometry-v1"

GATE_POSITIVE_COUNT = 20
GATE_NEGATIVE_COUNT = 99
GATE_HARD_NEGATIVE_COUNT = 33
GATE_THRESHOLD = 0.25
GATE_COPY_PROBABILITY = 0.5
CONTROL_REPLICATES = 999
GATE_POSITIVE_SEED = 33012101
GATE_NEGATIVE_SEED = 33012102
CONTROL_SEED = 33012103
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25
LAYOUT_LENGTHS = (7, 9, 5, 11, 8, 13, 6, 10, 12, 7, 9, 14, 5, 11)
PAGE_FIELDS = ("page", "rows", "equal_count", "comparison_count", "score")
ROW_FIELDS = ("row", "group", "values", "rune_count")
RUNE_TO_INDEX = {char: index for index, char in enumerate(RUNES)}
SOFT_SEPARATORS = frozenset("-.,")


class GateFailure(RuntimeError):
    """A failed synthetic gate makes the LP2 portion scientifically invalid."""


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
    applicable = []
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
            applicable.append(
                dict(page=page["page"], raw=raw, cipher=cipher)
            )
    if len(applicable) != 55:
        raise ValueError("Unexpected number of applicable pages")
    if [page["page"] for page in pages if not page["rune_count"]] != ["LP2/50"]:
        raise ValueError("Unexpected inapplicable page")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("Unexpected rune count")
    return applicable, metadata


def _finish_verifier_row(rows, values, segments):
    rows.append(
        dict(
            row=len(rows),
            group=segments[0] if values and len(set(segments)) == 1 else None,
            values=list(values),
            rune_count=len(values),
        )
    )


def derive_rows_for_verifier(raw):
    """Parse the public raw text with a verifier-only implementation."""
    rows = []
    values = []
    segment_ids = []
    segment = 0
    hard_pending = False
    for char in raw:
        if char in RUNE_TO_INDEX:
            if hard_pending:
                segment += 1
                hard_pending = False
            values.append(RUNE_TO_INDEX[char])
            segment_ids.append(segment)
        elif char == "/":
            _finish_verifier_row(rows, values, segment_ids)
            values = []
            segment_ids = []
        elif char.isspace() or char in SOFT_SEPARATORS:
            continue
        else:
            if 0x16A0 <= ord(char) <= 0x16FF:
                raise ValueError("Unregistered runic glyph in public raw page")
            hard_pending = True
    if values:
        _finish_verifier_row(rows, values, segment_ids)
    return rows


def verifier_metrics(rows):
    equal_count = 0
    comparison_count = 0
    for index in range(len(rows) - 1):
        left = rows[index]
        right = rows[index + 1]
        if not left["values"] or not right["values"]:
            continue
        if left["group"] is None or left["group"] != right["group"]:
            continue
        width = min(len(left["values"]), len(right["values"]))
        comparison_count += width
        equal_count += sum(
            left["values"][column] == right["values"][column]
            for column in range(width)
        )
    return dict(
        equal_count=equal_count,
        comparison_count=comparison_count,
        score=(equal_count / comparison_count if comparison_count else None),
    )


def raw_from_rows(rows):
    return "/".join("".join(RUNES[value] for value in row) for row in rows) + "/"


def positive_rows(rng):
    rows = []
    for row_index, length in enumerate(LAYOUT_LENGTHS):
        if row_index == 0:
            row = [rng.randrange(29) for _ in range(length)]
        else:
            previous = rows[-1]
            row = [
                previous[column]
                if column < len(previous) and rng.random() < GATE_COPY_PROBABILITY
                else rng.randrange(29)
                for column in range(length)
            ]
        rows.append(row)
    return rows


def negative_rows(rng, difficult=False):
    rows = []
    for length in LAYOUT_LENGTHS:
        if difficult:
            motif = [rng.randrange(29) for _ in range(5)]
            phase = rng.randrange(len(motif))
            row = [motif[(phase + column) % len(motif)] for column in range(length)]
        else:
            row = [rng.randrange(29) for _ in range(length)]
        rows.append(row)
    return rows


def synthetic_gate():
    positive_rng = random.Random(GATE_POSITIVE_SEED)
    negative_rng = random.Random(GATE_NEGATIVE_SEED)
    jobs = []
    answers = {}
    labels = {}
    for index in range(1, GATE_POSITIVE_COUNT + 1):
        rows = positive_rows(positive_rng)
        raw = raw_from_rows(rows)
        parsed_rows = derive_rows_for_verifier(raw)
        job_id = f"gate-positive-{index:02d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, raw=raw)]))
        answers[job_id] = dict(kind="positive", rows=rows, raw=raw, score=verifier_metrics(parsed_rows)["score"])
        labels[job_id] = "positive"
    difficult_start = GATE_NEGATIVE_COUNT - GATE_HARD_NEGATIVE_COUNT + 1
    for index in range(1, GATE_NEGATIVE_COUNT + 1):
        difficult = index >= difficult_start
        rows = negative_rows(negative_rng, difficult=difficult)
        raw = raw_from_rows(rows)
        parsed_rows = derive_rows_for_verifier(raw)
        job_id = f"gate-negative-{index:03d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, raw=raw)]))
        answers[job_id] = dict(
            kind="negative_hard" if difficult else "negative",
            rows=rows,
            raw=raw,
            score=verifier_metrics(parsed_rows)["score"],
        )
        labels[job_id] = "negative_hard" if difficult else "negative"
    if len(jobs) != GATE_POSITIVE_COUNT + GATE_NEGATIVE_COUNT:
        raise ValueError("H021 synthetic gate job count drifted")
    return jobs, answers, labels


def build_public(applicable_pages):
    gate_jobs, answers, labels = synthetic_gate()
    gate_jobs.append(
        dict(
            id="unsolved-page-reset",
            pages=[dict(page=page["page"], raw=page["raw"]) for page in applicable_pages],
        )
    )
    labels["unsolved-page-reset"] = "lp2"
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=gate_jobs), answers, labels


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H021 worker output fields")
    if output["status"] != "completed" or not output["read_guard_probe_passed"]:
        raise ValueError("H021 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output["jobs"]] != public_ids:
        raise ValueError("H021 worker omitted or reordered jobs")

    positive_ids = {job_id for job_id, answer in answers.items() if answer["kind"] == "positive"}
    negative_ids = {job_id for job_id, answer in answers.items() if answer["kind"].startswith("negative")}
    if len(positive_ids) != GATE_POSITIVE_COUNT or len(negative_ids) != GATE_NEGATIVE_COUNT:
        raise ValueError("H021 gate answer counts drifted")

    positive_checks = []
    page_checks = 0
    rune_checks = 0
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job.get("id") != public_job["id"]:
            raise ValueError("H021 worker job identity mismatch")
        public_pages = public_job["pages"]
        output_pages = output_job.get("pages")
        if len(output_pages) != len(public_pages):
            raise ValueError(f"H021 page coverage mismatch: {public_job['id']}")
        for public_page, actual_page in zip(public_pages, output_pages):
            expected_rows = derive_rows_for_verifier(public_page["raw"])
            expected_metrics = verifier_metrics(expected_rows)
            if set(actual_page) != set(PAGE_FIELDS):
                raise ValueError(f"H021 page output fields mismatch: {public_page['page']}")
            if actual_page["page"] != public_page["page"]:
                raise ValueError("H021 page identity mismatch")
            if actual_page["rows"] != expected_rows:
                raise ValueError(f"Independent H021 row parse mismatch: {public_page['page']}")
            for field in ("equal_count", "comparison_count"):
                if actual_page[field] != expected_metrics[field]:
                    raise ValueError(f"Independent H021 metric mismatch: {public_page['page']}")
            if not (
                actual_page["score"] is None
                and expected_metrics["score"] is None
                or actual_page["score"] is not None
                and expected_metrics["score"] is not None
                and math.isclose(actual_page["score"], expected_metrics["score"], abs_tol=1e-15)
            ):
                raise ValueError(f"Independent H021 score mismatch: {public_page['page']}")
            if public_job["id"] in positive_ids:
                answer = answers[public_job["id"]]
                if expected_rows != [
                    dict(row=index, group=0, values=list(row), rune_count=len(row))
                    for index, row in enumerate(answer["rows"])
                ]:
                    raise ValueError(f"H021 positive expected row mismatch: {public_page['page']}")
                if not math.isclose(actual_page["score"], answer["score"], abs_tol=1e-15):
                    raise ValueError(f"H021 positive expected score mismatch: {public_page['page']}")
                positive_checks.append(dict(job=public_job["id"], row_count=len(expected_rows)))
            page_checks += 1
            rune_checks += sum(row["rune_count"] for row in expected_rows)
    if {row["job"] for row in positive_checks} != positive_ids:
        raise ValueError("H021 positive validation is incomplete")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        positive_row_checks=positive_checks,
        page_checks=page_checks,
        rune_checks=rune_checks,
        independent_algorithm="separate raw-character row parser and common-ordinal metric",
    )


def gate_result(output, answers):
    output_map = {job["id"]: job for job in output["jobs"]}
    positive_scores = []
    negative_scores = []
    positive_exact = 0
    for job_id, answer in answers.items():
        actual_page = output_map[job_id]["pages"][0]
        score = actual_page["score"]
        exact = actual_page["rows"] == [
            dict(row=index, group=0, values=list(row), rune_count=len(row))
            for index, row in enumerate(answer["rows"])
        ]
        if answer["kind"] == "positive":
            positive_exact += int(exact)
            positive_scores.append(dict(job=job_id, score=score, exact=exact))
        else:
            negative_scores.append(
                dict(
                    job=job_id,
                    class_name=answer["kind"],
                    score=score,
                    false_accept=score is not None and score >= GATE_THRESHOLD,
                )
            )
    positive_passes = sum(
        item["exact"] and item["score"] is not None and item["score"] >= GATE_THRESHOLD
        for item in positive_scores
    )
    negative_false_accepts = sum(item["false_accept"] for item in negative_scores)
    hard_negative_scores = [item for item in negative_scores if item["class_name"] == "negative_hard"]
    return dict(
        status="passed" if positive_passes >= 18 and negative_false_accepts == 0 else "failed",
        positive_requested=GATE_POSITIVE_COUNT,
        positive_exact=positive_exact,
        positive_score_passes=positive_passes,
        negative_requested=GATE_NEGATIVE_COUNT,
        negative_false_accepts=negative_false_accepts,
        hard_negative_requested=len(hard_negative_scores),
        hard_negative_false_accepts=sum(item["false_accept"] for item in hard_negative_scores),
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
        negative_scope="No LP2 negative conclusion is valid when the fixed geometry gate fails.",
        limitation="The gate failure is retained for audit; the LP2 batch must be rerun only under a new frozen version.",
    )


def rotate_rows(rows, rng):
    rotated = []
    for row in rows:
        values = list(row["values"])
        if values:
            offset = rng.randrange(len(values))
            values = values[offset:] + values[:offset]
        rotated.append(
            dict(row=row["row"], group=row["group"], values=values, rune_count=len(values))
        )
    return rotated


def standardize(observed, controls):
    if len(observed) == 0 or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected H021 score shape")
    if any(len(row) != len(observed) for row in controls):
        raise ValueError("H021 control score width mismatch")
    values_by_unit = [[observed[index]] + [row[index] for row in controls] for index in range(len(observed))]
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


def save_checkpoint(path, *, completed, partial_path, frozen, rng, status, unit_count):
    frozen_value = json.loads(frozen.read_text(encoding="utf8"))
    checkpoint = dict(
        schema=1,
        status=status,
        completed=completed,
        last_replicate=completed,
        requested=CONTROL_REPLICATES,
        unit_count=unit_count,
        seed=CONTROL_SEED,
        partial_path=partial_path.name,
        partial_sha256=sha256(partial_path) if partial_path.exists() else None,
        frozen_sha256=sha256(frozen),
        code_version_digest=frozen_value["code_version"]["digest"],
        public_sha256=frozen_value["public_sha256"],
        rng_state_sha256=stable_digest(rng.getstate()),
        replay_rule="restart from seed and consume one independent circular row rotation per retained row per replicate",
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
            "reviews/auto-cycle-006.md",
            "reviews/attempt-004.md",
            "reviews/feed010-operational-metaphors.md",
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
        attempt="auto-cycle R011",
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
            raise ValueError("H021 specification is not preregistered")
        applicable_pages, metadata = load_pages()
        public, answers, labels = build_public(applicable_pages)
        source_paths = [
            SPEC_PATH.relative_to(ROOT).as_posix(),
            CORPUS_PATH.relative_to(ROOT).as_posix(),
            DATA_README_PATH.relative_to(ROOT).as_posix(),
            FEED_SPEC_PATH.relative_to(ROOT).as_posix(),
            FEED_REVIEW_PATH.relative_to(ROOT).as_posix(),
            H008_REVIEW_PATH.relative_to(ROOT).as_posix(),
        ]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        page_order = [page["page"] for page in applicable_pages]
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
                page_order=page_order,
                applicable_pages=page_order,
                excluded_pages=["LP2/50"],
                rune_count=12956,
                row_layout_lengths=list(LAYOUT_LENGTHS),
                gate=dict(
                    positive_count=GATE_POSITIVE_COUNT,
                    negative_count=GATE_NEGATIVE_COUNT,
                    hard_negative_count=GATE_HARD_NEGATIVE_COUNT,
                    threshold=GATE_THRESHOLD,
                    copy_probability=GATE_COPY_PROBABILITY,
                    positive_seed=GATE_POSITIVE_SEED,
                    negative_seed=GATE_NEGATIVE_SEED,
                ),
                control_replicates=CONTROL_REPLICATES,
                control_seed=CONTROL_SEED,
                alpha=ALPHA,
                tie_tolerance=TIE_TOLERANCE,
                total_wall_seconds=WALL_SECONDS,
                checkpoint_every=CHECKPOINT_EVERY,
                expected_positive_job_ids=sorted(positive_ids for positive_ids in answers if answers[positive_ids]["kind"] == "positive"),
                expected_answers_sha256=sha256(run / "verifier-only" / "answers.json"),
                public_sha256=stable_digest(public),
            ),
        )
        record.update(execution_started=True, source_files_verified=source_count, frozen_sha256=sha256(frozen))
        write_json(run / "record.json", record)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("H021 deadline expired before worker")
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
            raise TimeoutError("H021 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H021 worker failed; see worker-execution.json")
        output = json.loads(execution["stdout"])
        write_json(run / "worker-output.json", output)
        verification = verify_worker(public, output, answers)
        write_json(run / "independent-verification.json", verification)
        gate = gate_result(output, answers)
        write_json(run / "power-gate.json", gate)
        if not gate_allows_lp2(gate):
            if time.monotonic() >= deadline:
                raise TimeoutError("H021 wall budget exceeded after failed power gate")
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
            raise GateFailure("H021 power gate failed; LP2 scan was not interpreted")

        unsolved = next(job for job in output["jobs"] if job["id"] == "unsolved-page-reset")
        observed_rows = []
        for row in unsolved["pages"]:
            observed_rows.append(
                dict(
                    page=row["page"],
                    rows=row["rows"],
                    equal_count=row["equal_count"],
                    comparison_count=row["comparison_count"],
                    score=row["score"],
                )
            )
        if [row["page"] for row in observed_rows] != page_order:
            raise ValueError("Observed H021 page order changed")
        valid_rows = [row for row in observed_rows if row["score"] is not None]
        unit_order = [row["page"] for row in valid_rows]
        if not unit_order:
            raise ValueError("H021 has no applicable page-level score unit")
        observed = [row["score"] for row in valid_rows]
        write_json(
            run / "observed.json",
            dict(
                algorithm="slash-row common-ordinal equality; hard/empty barriers",
                pages=observed_rows,
                valid_unit_order=unit_order,
                score_vector=observed,
                score_vector_sha256=stable_digest(observed),
            ),
        )

        layouts = [derive_rows_for_verifier(page["raw"]) for page in applicable_pages]
        controls = []
        partial_path = run / "control-scores.partial.jsonl"
        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"H021 wall budget exceeded after {len(controls)} controls")
            metrics_by_page = [verifier_metrics(rotate_rows(rows, rng))["score"] for rows in layouts]
            metrics = [metrics_by_page[page_order.index(page)] for page in unit_order]
            if any(metric is None for metric in metrics):
                raise ValueError("H021 control lost a valid score unit")
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
                    unit_count=len(unit_order),
                )
                write_json(run / "record.json", record)
        if time.monotonic() >= deadline:
            raise TimeoutError("H021 wall budget exceeded after final control")
        write_json(
            run / "control-scores.json",
            dict(
                schema=1,
                algorithm="independent circular shift of each retained row",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=unit_order,
                score_rows=controls,
            ),
        )
        stats = standardize(observed, controls)
        stat_rows = []
        for page, metric, z, p, std in zip(unit_order, observed, stats["observed_z"], stats["p_adjusted"], stats["stds"]):
            status = "zero_variance" if std == 0 else ("lead" if p <= ALPHA else "not_detected")
            stat_rows.append(
                dict(page=page, score=metric, statistic_status=status, candidate=status == "lead", z=z, p_adjusted=p)
            )
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"]))[:10]
        summary_status = "inconclusive" if leads else "negative"
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
                inapplicable_score_pages=[page["page"] for page in observed_rows if page["score"] is None],
                runes=12956,
                score_units=len(unit_order),
                control_replicates=len(controls),
                unsolved_page_candidates=[row["page"] for row in leads],
            ),
            leads=leads,
            strongest=strongest,
            statistic_rows=stat_rows,
            statistics=stats,
            interpretation="The fixed slash-row relation is a structural diagnostic; it does not decode plaintext or identify a key.",
            negative_scope="Only H021's slash row boundary, left ordinal, hard/empty barriers, common-ordinal equality statistic and independent per-row circular-shift null.",
            limitation="Physical pixel columns are unavailable because the retained image bounding boxes are unlocated; LP2/50 literal grid is unexecuted.",
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("H021 wall budget exceeded before statistics finalization")
        write_json(run / "statistics.json", summary)
        if time.monotonic() >= deadline:
            summary["status"] = "timeout"
            summary["scientific_result_valid"] = False
            summary["limitation"] += " Final statistics write crossed the monotonic deadline."
            write_json(run / "statistics.json", summary)
            raise TimeoutError("H021 wall budget exceeded during statistics finalization")
        record.update(
            status=summary["status"],
            result=dict(leads=len(leads), gate_status=gate["status"], strongest=strongest[:3]),
            actual_coverage=summary["coverage"],
            unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"],
        )
        if code_snapshot(ROOT) != snapshot or any(sha256(ROOT / path) != value for path, value in source_hashes.items()):
            raise ValueError("Frozen H021 code or source input changed during execution")
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
