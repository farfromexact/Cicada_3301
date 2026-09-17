"""Run R013/H023 with a gate-only dispatch followed by optional LP2 dispatch."""

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


SPEC_PATH = ROOT / "hypotheses/H023-row-edge-interior-g-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
DATA_README_PATH = ROOT / "data/README.md"
H021_SPEC_PATH = ROOT / "hypotheses/H021-row-alignment-geometry-v1.json"
H022_SPEC_PATH = ROOT / "hypotheses/H022-snake-row-bigram-v1.json"
R011_REVIEW_PATH = ROOT / "reviews/auto-cycle-006.md"
R012_REVIEW_PATH = ROOT / "reviews/auto-cycle-007.md"
R013_REVIEW_PATH = ROOT / "reviews/auto-cycle-008.md"
FEED_REVIEW_PATH = ROOT / "reviews/feed010-operational-metaphors.md"
WORKER_PATH = ROOT / "scripts/attempt18_row_edge_worker_v1.py"
HYPOTHESIS = "H023-row-edge-interior-g-v1"

GATE_POSITIVE_COUNT = 20
GATE_NEGATIVE_COUNT = 99
GATE_NEGATIVE_CLASS_COUNT = 33
GATE_THRESHOLD = 80.0
GATE_EDGE_SET = (0, 1, 2, 3, 4, 5, 6)
GATE_EDGE_PROBABILITY = 0.8
CONTROL_REPLICATES = 999
GATE_POSITIVE_SEED = 33012301
GATE_NEGATIVE_SEED = 33012302
CONTROL_SEED = 33012303
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25
LAYOUT_LENGTHS = tuple(range(48, 56)) * 6
PAGE_FIELDS = ("page", "rows", "eligible_row_count", "edge_count", "interior_count", "g_stat")
ROW_FIELDS = ("row", "group", "values", "rune_count")
RUNE_TO_INDEX = {char: index for index, char in enumerate(RUNES)}
SOFT_SEPARATORS = frozenset("-.,")


class GateFailure(RuntimeError):
    """A failed synthetic gate makes the LP2 portion scientifically invalid."""


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")


def stable_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")
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
        rune_values = indices(raw)
        if len(rune_values) != page["rune_count"]:
            raise ValueError(f"Corpus rune count mismatch: {page['page']}")
        metadata.append(dict(page=page["page"], page_number=page["page_number"], rune_count=len(rune_values), raw_sha256=raw_hash, source=page["source"], source_sha256=page["source_sha256"], image_path=page["image_path"], image_sha256=page["image_sha256"], applicability=page["applicability"]))
        if rune_values:
            applicable.append(dict(page=page["page"], raw=raw, cipher=rune_values))
    if len(applicable) != 55:
        raise ValueError("Unexpected number of applicable pages")
    if [page["page"] for page in pages if not page["rune_count"]] != ["LP2/50"]:
        raise ValueError("Unexpected inapplicable page")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("Unexpected rune count")
    return applicable, metadata


def _append_verifier_row(rows, values, segments):
    rows.append(dict(row=len(rows), group=segments[0] if values and len(set(segments)) == 1 else None, values=list(values), rune_count=len(values)))


def derive_rows_for_verifier(raw):
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
            _append_verifier_row(rows, values, segment_ids)
            values = []
            segment_ids = []
        elif char.isspace() or char in SOFT_SEPARATORS:
            continue
        else:
            if 0x16A0 <= ord(char) <= 0x16FF:
                raise ValueError("Unregistered runic glyph in public raw page")
            hard_pending = True
    if values:
        _append_verifier_row(rows, values, segment_ids)
    return rows


def verifier_g(rows):
    counts = [[0, 0] for _ in range(29)]
    eligible_rows = 0
    edge_count = 0
    interior_count = 0
    for row in rows:
        if row["rune_count"] < 3 or row["group"] is None:
            continue
        eligible_rows += 1
        for value in (row["values"][0], row["values"][-1]):
            counts[value][0] += 1
        for value in row["values"][1:-1]:
            counts[value][1] += 1
        edge_count += 2
        interior_count += row["rune_count"] - 2
    total = edge_count + interior_count
    statistic = None
    if total:
        row_totals = [sum(columns) for columns in counts]
        column_totals = [sum(counts[row][column] for row in range(29)) for column in range(2)]
        statistic = 0.0
        for row in range(29):
            for column in range(2):
                observed = counts[row][column]
                expected = row_totals[row] * column_totals[column] / total
                if observed:
                    statistic += 2.0 * observed * math.log(observed / expected)
    return dict(eligible_row_count=eligible_rows, edge_count=edge_count, interior_count=interior_count, g_stat=statistic)


def raw_from_rows(rows):
    return "/".join("".join(RUNES[value] for value in row) for row in rows) + "/"


def positive_rows(rng):
    rows = []
    for length in LAYOUT_LENGTHS:
        row = []
        for position in range(length):
            if position in (0, length - 1):
                value = rng.choice(GATE_EDGE_SET) if rng.random() < GATE_EDGE_PROBABILITY else rng.randrange(29)
            else:
                value = rng.randrange(29)
            row.append(value)
        rows.append(row)
    return rows


def uniform_rows(rng):
    return [[rng.randrange(29) for _ in range(length)] for length in LAYOUT_LENGTHS]


def heterogeneous_rows(rng):
    rows = []
    for length in LAYOUT_LENGTHS:
        support = rng.sample(range(29), 7)
        rows.append([support[rng.randrange(len(support))] for _ in range(length)])
    return rows


def fixed_seven_rows(rng):
    return [[GATE_EDGE_SET[rng.randrange(len(GATE_EDGE_SET))] for _ in range(length)] for length in LAYOUT_LENGTHS]


def synthetic_gate():
    positive_rng = random.Random(GATE_POSITIVE_SEED)
    negative_rng = random.Random(GATE_NEGATIVE_SEED)
    jobs = []
    answers = {}
    labels = {}
    for index in range(1, GATE_POSITIVE_COUNT + 1):
        rows = positive_rows(positive_rng)
        raw = raw_from_rows(rows)
        parsed = derive_rows_for_verifier(raw)
        job_id = f"gate-positive-{index:02d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, raw=raw)]))
        answers[job_id] = dict(kind="positive", rows=rows, raw=raw, metrics=verifier_g(parsed))
        labels[job_id] = "positive"
    negative_generators = (uniform_rows, heterogeneous_rows, fixed_seven_rows)
    negative_kinds = ("negative_uniform", "negative_row_heterogeneous", "negative_fixed_seven")
    for index in range(1, GATE_NEGATIVE_COUNT + 1):
        class_index = (index - 1) // GATE_NEGATIVE_CLASS_COUNT
        kind = negative_kinds[class_index]
        rows = negative_generators[class_index](negative_rng)
        raw = raw_from_rows(rows)
        parsed = derive_rows_for_verifier(raw)
        job_id = f"gate-negative-{index:03d}"
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, raw=raw)]))
        answers[job_id] = dict(kind=kind, rows=rows, raw=raw, metrics=verifier_g(parsed))
        labels[job_id] = kind
    if len(jobs) != GATE_POSITIVE_COUNT + GATE_NEGATIVE_COUNT:
        raise ValueError("H023 synthetic gate job count drifted")
    return jobs, answers, labels


def build_gate_public():
    jobs, answers, labels = synthetic_gate()
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=jobs), answers, labels


def build_lp2_public(applicable_pages):
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=[dict(id="unsolved-page-reset", pages=[dict(page=page["page"], raw=page["raw"]) for page in applicable_pages])])


def _expected_answer_rows(answer):
    return [dict(row=index, group=0, values=list(values), rune_count=len(values)) for index, values in enumerate(answer["rows"])]


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H023 worker output fields")
    if output["status"] != "completed" or not output["read_guard_probe_passed"]:
        raise ValueError("H023 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output["jobs"]] != public_ids:
        raise ValueError("H023 worker omitted or reordered jobs")
    positive_ids = {job_id for job_id, answer in answers.items() if answer["kind"] == "positive"}
    if answers and len(positive_ids) != GATE_POSITIVE_COUNT:
        raise ValueError("H023 gate answer counts drifted")
    positive_checks = []
    page_checks = 0
    rune_checks = 0
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job.get("id") != public_job["id"] or len(output_job.get("pages", [])) != len(public_job["pages"]):
            raise ValueError(f"H023 job/page coverage mismatch: {public_job['id']}")
        for public_page, actual_page in zip(public_job["pages"], output_job["pages"]):
            expected_rows = derive_rows_for_verifier(public_page["raw"])
            expected_metrics = verifier_g(expected_rows)
            if set(actual_page) != set(PAGE_FIELDS) or actual_page["page"] != public_page["page"]:
                raise ValueError(f"H023 page output mismatch: {public_page['page']}")
            if actual_page["rows"] != expected_rows:
                raise ValueError(f"Independent H023 row mismatch: {public_page['page']}")
            for field in ("eligible_row_count", "edge_count", "interior_count"):
                if actual_page[field] != expected_metrics[field]:
                    raise ValueError(f"Independent H023 count mismatch: {public_page['page']}")
            if expected_metrics["g_stat"] is None or actual_page["g_stat"] is None:
                if expected_metrics["g_stat"] is not None or actual_page["g_stat"] is not None:
                    raise ValueError(f"Independent H023 statistic mismatch: {public_page['page']}")
            elif not math.isclose(actual_page["g_stat"], expected_metrics["g_stat"], abs_tol=1e-12):
                raise ValueError(f"Independent H023 statistic mismatch: {public_page['page']}")
            if public_job["id"] in positive_ids:
                answer = answers[public_job["id"]]
                if actual_page["rows"] != _expected_answer_rows(answer):
                    raise ValueError(f"H023 positive row mismatch: {public_page['page']}")
                for field in PAGE_FIELDS[2:]:
                    expected_value = answer["metrics"][field]
                    if isinstance(expected_value, float):
                        if not math.isclose(actual_page[field], expected_value, abs_tol=1e-12):
                            raise ValueError(f"H023 positive metric mismatch: {public_page['page']}")
                    elif actual_page[field] != expected_value:
                        raise ValueError(f"H023 positive metric mismatch: {public_page['page']}")
                positive_checks.append(dict(job=public_job["id"], row_count=len(expected_rows)))
            page_checks += 1
            rune_checks += sum(row["rune_count"] for row in expected_rows)
    if answers and {row["job"] for row in positive_checks} != positive_ids:
        raise ValueError("H023 positive validation is incomplete")
    return dict(status="passed", worker_jobs=len(public["jobs"]), positive_row_checks=positive_checks, page_checks=page_checks, rune_checks=rune_checks, independent_algorithm="separate raw-character parser and pooled 29x2 G calculation")


def gate_result(output, answers):
    output_map = {job["id"]: job for job in output["jobs"]}
    positives = []
    negatives = []
    for job_id, answer in answers.items():
        page = output_map[job_id]["pages"][0]
        exact = page["rows"] == _expected_answer_rows(answer)
        if answer["kind"] == "positive":
            positives.append(dict(job=job_id, g_stat=page["g_stat"], exact=exact))
        else:
            negatives.append(dict(job=job_id, class_name=answer["kind"], g_stat=page["g_stat"], false_accept=page["g_stat"] is not None and page["g_stat"] >= GATE_THRESHOLD))
    positive_passes = sum(item["exact"] and item["g_stat"] is not None and item["g_stat"] >= GATE_THRESHOLD for item in positives)
    negative_false_accepts = sum(item["false_accept"] for item in negatives)
    return dict(status="passed" if positive_passes >= 18 and negative_false_accepts == 0 else "failed", positive_requested=GATE_POSITIVE_COUNT, positive_exact=sum(item["exact"] for item in positives), positive_score_passes=positive_passes, negative_requested=GATE_NEGATIVE_COUNT, negative_false_accepts=negative_false_accepts, negative_class_false_accepts={class_name: sum(item["false_accept"] for item in negatives if item["class_name"] == class_name) for class_name in sorted({item["class_name"] for item in negatives})}, threshold=GATE_THRESHOLD, positive_scores=positives, negative_scores=negatives)


def gate_allows_lp2(gate):
    return (
        gate.get("status") == "passed"
        and gate.get("positive_score_passes") >= 18
        and gate.get("negative_false_accepts") == 0
    )


def build_gate_failure_summary(gate, verification_status):
    return dict(status="inconclusive", hypothesis=HYPOTHESIS, verification_status=verification_status, lp2_status="not_dispatched_gate_failed", power_gate=gate, controls_completed=0, coverage=dict(pages=0, applicable_pages=0, requested_pages=55, excluded_pages=["LP2/50"], runes=0, requested_runes=12956, score_units=0, requested_score_units=55, control_replicates=0, requested_control_replicates=CONTROL_REPLICATES, unsolved_page_candidates=[]), leads=[], strongest=[], statistic_rows=[], statistics=None, interpretation="The synthetic measurement gate failed; LP2 was not dispatched to the worker.", negative_scope="No LP2 negative conclusion is valid when the fixed edge/interior gate fails.", limitation="The gate failure is retained for audit; no LP2 public job was sent.")


def random_rotate_rows(rows, rng):
    result = []
    for row in rows:
        values = list(row["values"])
        if values:
            offset = rng.randrange(len(values))
            values = values[offset:] + values[:offset]
        result.append(dict(row=row["row"], group=row["group"], values=values, rune_count=len(values)))
    return result


def standardize(observed, controls):
    if not observed or len(controls) != CONTROL_REPLICATES or any(len(row) != len(observed) for row in controls):
        raise ValueError("Unexpected H023 score shape")
    values_by_unit = [[observed[index]] + [row[index] for row in controls] for index in range(len(observed))]
    means, stds = [], []
    for values in values_by_unit:
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(math.sqrt(variance))
    observed_z = [(value - mean) / std if std > 0 else 0.0 for value, mean, std in zip(observed, means, stds)]
    control_max = [max((value - mean) / std if std > 0 else 0.0 for value, mean, std in zip(row, means, stds)) for row in controls]
    p_values = [(1 + sum(max_z >= z - TIE_TOLERANCE for max_z in control_max)) / (len(control_max) + 1) if std > 0 else 1.0 for z, std in zip(observed_z, stds)]
    return dict(means=means, stds=stds, observed_z=observed_z, control_max_z=control_max, p_adjusted=p_values)


def save_checkpoint(path, *, completed, partial_path, frozen, rng, status, unit_count):
    frozen_value = json.loads(frozen.read_text(encoding="utf8"))
    checkpoint = dict(schema=1, status=status, completed=completed, last_replicate=completed, requested=CONTROL_REPLICATES, unit_count=unit_count, seed=CONTROL_SEED, partial_path=partial_path.name, partial_sha256=sha256(partial_path) if partial_path.exists() else None, frozen_sha256=sha256(frozen), code_version_digest=frozen_value["code_version"]["digest"], public_sha256=frozen_value["lp2_public_sha256"], rng_state_sha256=stable_digest(rng.getstate()), replay_rule="restart from seed and consume one independent circular rotation per retained row per replicate")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")
    os.replace(temporary, path)


def archive_run(run, snapshot):
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / path for path in snapshot["files"]]
    paths.extend(path for directory in ("sources", "data", "hypotheses", "research") for path in (ROOT / directory).rglob("*") if path.is_file())
    paths.extend(path for path in run.rglob("*") if path.is_file() and path != archive)
    knowledge = json.loads((ROOT / "research/knowledge.json").read_text(encoding="utf8"))
    paths.extend(ROOT / entry["artifact"] for entry in knowledge["experiments"])
    paths.extend(ROOT / name for name in ("README.md", "AGENTS.md", "STATE.md", "reviews/auto-cycle-006.md", "reviews/auto-cycle-007.md", "reviews/auto-cycle-008.md", "reviews/attempt-004.md", "reviews/feed010-operational-metaphors.md"))
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive), bytes=archive.stat().st_size)


def _execute_worker(public, run, prefix, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"H023 deadline expired before {prefix} worker")
    execution = execute([sys.executable, "-I", "-S", str(WORKER_PATH)], cwd=ROOT, timeout=remaining, stdin=json.dumps(public))
    write_json(run / f"worker-{prefix}-execution.json", execution)
    (run / f"worker-{prefix}-stdout.json").write_text(execution["stdout"], encoding="utf8")
    (run / f"worker-{prefix}-stderr.txt").write_text(execution["stderr"], encoding="utf8")
    if execution["status"] == "timeout":
        raise TimeoutError(f"H023 {prefix} worker timed out")
    if execution["status"] != "completed":
        raise RuntimeError(f"H023 {prefix} worker failed; see worker-{prefix}-execution.json")
    output = json.loads(execution["stdout"])
    write_json(run / f"worker-{prefix}-output.json", output)
    return output


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
    record = dict(schema=1, attempt="auto-cycle R013", hypothesis=HYPOTHESIS, status="running", started_at_utc=started_at.isoformat(), python=sys.version, executable=sys.executable, platform=platform.platform(), code_version=snapshot, controls_completed=0, unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        if spec.get("id") != HYPOTHESIS or spec.get("status") != "preregistered":
            raise ValueError("H023 specification is not preregistered")
        applicable_pages, metadata = load_pages()
        gate_public, answers, labels = build_gate_public()
        source_paths = [SPEC_PATH.relative_to(ROOT).as_posix(), CORPUS_PATH.relative_to(ROOT).as_posix(), DATA_README_PATH.relative_to(ROOT).as_posix(), H021_SPEC_PATH.relative_to(ROOT).as_posix(), H022_SPEC_PATH.relative_to(ROOT).as_posix(), R011_REVIEW_PATH.relative_to(ROOT).as_posix(), R012_REVIEW_PATH.relative_to(ROOT).as_posix(), R013_REVIEW_PATH.relative_to(ROOT).as_posix(), FEED_REVIEW_PATH.relative_to(ROOT).as_posix()]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        page_order = [page["page"] for page in applicable_pages]
        write_json(run / "inputs.json", dict(schema=1, derived_at_utc=started_at.isoformat(), corpus_version="attempt1-corpus-v1", pages=metadata, gate_public_job_ids=[job["id"] for job in gate_public["jobs"]], public_sha256=stable_digest(gate_public), job_labels=labels))
        write_json(run / "public-gate.json", gate_public)
        write_json(run / "verifier-only" / "answers.json", answers)
        frozen = run / "frozen.json"
        write_json(frozen, dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), specification=spec, source_hashes=source_hashes, code_version=snapshot, page_order=page_order, applicable_pages=page_order, excluded_pages=["LP2/50"], rune_count=12956, gate=dict(positive_count=GATE_POSITIVE_COUNT, negative_count=GATE_NEGATIVE_COUNT, negative_class_count=GATE_NEGATIVE_CLASS_COUNT, threshold=GATE_THRESHOLD, edge_set=list(GATE_EDGE_SET), edge_probability=GATE_EDGE_PROBABILITY, positive_seed=GATE_POSITIVE_SEED, negative_seed=GATE_NEGATIVE_SEED), control_replicates=CONTROL_REPLICATES, control_seed=CONTROL_SEED, alpha=ALPHA, tie_tolerance=TIE_TOLERANCE, total_wall_seconds=WALL_SECONDS, checkpoint_every=CHECKPOINT_EVERY, gate_public_sha256=stable_digest(gate_public), expected_answers_sha256=sha256(run / "verifier-only" / "answers.json")))
        record.update(execution_started=True, source_files_verified=source_count, frozen_sha256=sha256(frozen))
        write_json(run / "record.json", record)

        gate_output = _execute_worker(gate_public, run, "gate", deadline)
        gate_verification = verify_worker(gate_public, gate_output, answers)
        write_json(run / "independent-verification-gate.json", gate_verification)
        gate = gate_result(gate_output, answers)
        write_json(run / "power-gate.json", gate)
        if not gate_allows_lp2(gate):
            if time.monotonic() >= deadline:
                raise TimeoutError("H023 wall budget exceeded after failed power gate")
            summary = build_gate_failure_summary(gate, gate_verification["status"])
            write_json(run / "statistics.json", summary)
            write_json(run / "lp2-skipped.json", dict(status="skipped", reason="power_gate_failed", gate_worker_pages=gate_verification["page_checks"], lp2_dispatched=False, power_gate_sha256=sha256(run / "power-gate.json")))
            record.update(status="inconclusive", result=dict(gate_status=gate["status"], lp2_dispatched=False), actual_coverage=summary["coverage"], unsolved_page_candidates=[])
            raise GateFailure("H023 power gate failed; LP2 was not dispatched")

        if time.monotonic() >= deadline:
            raise TimeoutError("H023 wall budget exceeded before LP2 dispatch")
        lp2_public = build_lp2_public(applicable_pages)
        write_json(run / "public-lp2.json", lp2_public)
        frozen_lp2 = run / "frozen-lp2.json"
        frozen_data = json.loads(frozen.read_text(encoding="utf8"))
        frozen_data.update(lp2_public_sha256=stable_digest(lp2_public), lp2_job_id="unsolved-page-reset", lp2_dispatch_after_gate=True, parent_frozen_sha256=sha256(frozen))
        write_json(frozen_lp2, frozen_data)
        lp2_output = _execute_worker(lp2_public, run, "lp2", deadline)
        lp2_verification = verify_worker(lp2_public, lp2_output, {})
        write_json(run / "independent-verification-lp2.json", lp2_verification)
        if gate_verification["status"] != "passed" or lp2_verification["status"] != "passed":
            raise ValueError("H023 independent verification did not pass")

        unsolved = lp2_output["jobs"][0]
        observed_rows = [dict(page=row["page"], rows=row["rows"], eligible_row_count=row["eligible_row_count"], edge_count=row["edge_count"], interior_count=row["interior_count"], g_stat=row["g_stat"]) for row in unsolved["pages"]]
        if [row["page"] for row in observed_rows] != page_order:
            raise ValueError("Observed H023 page order changed")
        valid_rows = [row for row in observed_rows if row["g_stat"] is not None]
        unit_order = [row["page"] for row in valid_rows]
        if not unit_order:
            raise ValueError("H023 has no applicable page-level score unit")
        observed = [row["g_stat"] for row in valid_rows]
        write_json(run / "observed.json", dict(algorithm="pooled row-edge/interior G statistic", pages=observed_rows, valid_unit_order=unit_order, score_vector=observed, score_vector_sha256=stable_digest(observed)))

        layouts = {page["page"]: derive_rows_for_verifier(page["raw"]) for page in applicable_pages}
        controls = []
        partial_path = run / "control-scores.partial.jsonl"
        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"H023 wall budget exceeded after {len(controls)} controls")
            metrics_by_page = {page: verifier_g(random_rotate_rows(layouts[page], rng))["g_stat"] for page in page_order}
            metrics = [metrics_by_page[page] for page in unit_order]
            if any(metric is None for metric in metrics):
                raise ValueError("H023 control lost a valid score unit")
            controls.append(metrics)
            append_jsonl(partial_path, dict(replicate=replicate, metrics=metrics, metrics_sha256=stable_digest(metrics), rng_state_sha256=stable_digest(rng.getstate())))
            record["controls_completed"] = replicate
            if replicate % CHECKPOINT_EVERY == 0 or replicate == CONTROL_REPLICATES:
                save_checkpoint(run / "control-checkpoint.json", completed=replicate, partial_path=partial_path, frozen=frozen_lp2, rng=rng, status="complete" if replicate == CONTROL_REPLICATES else "partial", unit_count=len(unit_order))
                write_json(run / "record.json", record)
        if time.monotonic() >= deadline:
            raise TimeoutError("H023 wall budget exceeded after final control")
        write_json(run / "control-scores.json", dict(schema=1, algorithm="independent circular rotation of every retained row", seed=CONTROL_SEED, requested=CONTROL_REPLICATES, completed=len(controls), unit_order=unit_order, score_rows=controls))
        stats = standardize(observed, controls)
        stat_rows = []
        for page, metric, z, p, std in zip(unit_order, observed, stats["observed_z"], stats["p_adjusted"], stats["stds"]):
            status = "zero_variance" if std == 0 else ("lead" if p <= ALPHA else "not_detected")
            stat_rows.append(dict(page=page, g_stat=metric, statistic_status=status, candidate=status == "lead", z=z, p_adjusted=p))
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["page"]))[:10]
        summary = dict(status="inconclusive" if leads else "negative", hypothesis=HYPOTHESIS, verification_status="passed", power_gate=gate, controls_completed=len(controls), coverage=dict(pages=55, applicable_pages=55, excluded_pages=["LP2/50"], inapplicable_score_pages=[row["page"] for row in observed_rows if row["g_stat"] is None], runes=12956, score_units=len(unit_order), control_replicates=len(controls), unsolved_page_candidates=[row["page"] for row in leads]), leads=leads, strongest=strongest, statistic_rows=stat_rows, statistics=stats, interpretation="The fixed row-edge/interior G statistic is a structural diagnostic; it does not decode plaintext or identify a key.", negative_scope="Only H023's slash row boundary, hard-segment row eligibility, combined first/last edge mask, pooled 29x2 G statistic and independent per-row circular-shift null.", limitation="Physical pixel columns are unavailable because retained image bounding boxes are unlocated; LP2/50 literal grid is unexecuted.")
        if time.monotonic() >= deadline:
            raise TimeoutError("H023 wall budget exceeded before statistics finalization")
        write_json(run / "statistics.json", summary)
        if time.monotonic() >= deadline:
            summary["status"] = "timeout"
            summary["scientific_result_valid"] = False
            summary["limitation"] += " Final statistics write crossed the monotonic deadline."
            write_json(run / "statistics.json", summary)
            raise TimeoutError("H023 wall budget exceeded during statistics finalization")
        record.update(status=summary["status"], result=dict(leads=len(leads), gate_status=gate["status"], lp2_dispatched=True, strongest=strongest[:3]), actual_coverage=summary["coverage"], unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"])
        if code_snapshot(ROOT) != snapshot or any(sha256(ROOT / path) != value for path, value in source_hashes.items()):
            raise ValueError("Frozen H023 code or source input changed during execution")
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
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"], "controls_completed": record.get("controls_completed"), "unsolved_page_candidates": record.get("unsolved_page_candidates"), "elapsed_seconds": record.get("elapsed_seconds"), "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
