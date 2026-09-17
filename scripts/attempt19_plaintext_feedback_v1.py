"""Run R014/H025 with a gate-only dispatch followed by optional LP2 dispatch."""

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
from lp_lab.runes import indices
from lp_lab.synthetic import encode_text


SPEC_PATH = ROOT / "hypotheses/H025-plaintext-feedback-v1.json"
H017_SPEC_PATH = ROOT / "hypotheses/H017-ciphertext-feedback-v1.json"
H009_SPEC_PATH = ROOT / "hypotheses/H009-short-scorer-calibration-v1.json"
H023_SPEC_PATH = ROOT / "hypotheses/H023-row-edge-interior-g-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
HELDOUT_PATH = ROOT / "data/synthetic/heldout.txt"
R013_REVIEW_PATH = ROOT / "reviews/auto-cycle-008.md"
R014_REVIEW_PATH = ROOT / "reviews/auto-cycle-009.md"
WORKER_PATH = ROOT / "scripts/attempt19_plaintext_feedback_worker_v1.py"
HYPOTHESIS = "H025-plaintext-feedback-v1"

GATE_POSITIVE_COUNT = 20
GATE_NEGATIVE_COUNT = 99
GATE_NEGATIVE_CLASS_COUNT = 33
GATE_THRESHOLD = -5.9
GATE_LENGTHS = (
    262,
    266,
    201,
    217,
    261,
    263,
    196,
    208,
    255,
    268,
    263,
    273,
    261,
    272,
    137,
    159,
    267,
    273,
    260,
    271,
)
GATE_POSITIVE_SEED = 33012501
GATE_NEGATIVE_SEED = 33012502
CONTROL_SEED = 33012503
CONTROL_REPLICATES = 999
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25
EXPECTED_POSITIVE_JOB_IDS = frozenset(
    f"gate-positive-{index:02d}" for index in range(1, GATE_POSITIVE_COUNT + 1)
)
PAGE_FIELDS = ("page", "rune_count", "decoded_indices", "initial_previous_plain")


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


def scorer_basis():
    training = encode_text(TRAIN_PATH.read_text(encoding="utf8"))
    counts = [[0 for _ in range(29)] for _ in range(29)]
    for left, right in zip(training, training[1:]):
        counts[left][right] += 1
    pair_count = max(0, len(training) - 1)
    denominator = pair_count + 29 * 29
    weights = [
        [math.log((counts[left][right] + 1) / denominator) for right in range(29)]
        for left in range(29)
    ]
    return training, counts, weights


def score(decoded, weights):
    if len(decoded) < 2:
        return None
    value = sum(weights[left][right] for left, right in zip(decoded, decoded[1:]))
    return value / (len(decoded) - 1)


def independent_decode(cipher):
    """Direct P[i]=(C[i]-P[i-1]) mod29, separate from the worker."""
    previous_plain = 0
    decoded = []
    for value in cipher:
        if type(value) is not int or not 0 <= value < 29:
            raise ValueError("Cipher outside rune domain")
        current_plain = (value - previous_plain) % 29
        decoded.append(current_plain)
        previous_plain = current_plain
    return decoded


def independent_encrypt(plaintext):
    """Direct C[i]=(P[i]+P[i-1]) mod29, separate from the worker."""
    previous_plain = 0
    cipher = []
    for value in plaintext:
        if type(value) is not int or not 0 <= value < 29:
            raise ValueError("Plaintext outside rune domain")
        cipher.append((value + previous_plain) % 29)
        previous_plain = value
    return cipher


def independent_cumulative_encrypt(plaintext):
    """H017's wrong-mechanism control, kept verifier-only."""
    previous_cipher = 0
    cipher = []
    for value in plaintext:
        previous_cipher = (previous_cipher + value) % 29
        cipher.append(previous_cipher)
    return cipher


def positive_plaintext(heldout, index, length):
    start = index * 37
    plaintext = list(heldout[start : start + length])
    if len(plaintext) != length:
        raise ValueError("H025 heldout window is shorter than the frozen gate length")
    plaintext[0] = 0
    if index == 1:
        plaintext[1] = 0
    return plaintext


def synthetic_gate(heldout, weights):
    if len(heldout) < max(index * 37 + length for index, length in enumerate(GATE_LENGTHS)):
        raise ValueError("H025 heldout source is too short")
    positive_jobs = []
    answers = {}
    labels = {}
    positive_plaintexts = []
    for index, length in enumerate(GATE_LENGTHS):
        plaintext = positive_plaintext(heldout, index, length)
        cipher = independent_encrypt(plaintext)
        job_id = f"gate-positive-{index + 1:02d}"
        positive_jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        answers[job_id] = dict(
            kind="positive",
            plaintext=plaintext,
            cipher=cipher,
            score=score(plaintext, weights),
        )
        labels[job_id] = "positive"
        positive_plaintexts.append(plaintext)

    negative_rng = random.Random(GATE_NEGATIVE_SEED)
    negative_jobs = []
    negative_kinds = (
        "negative_uniform_ciphertext",
        "negative_wrong_h017_cumulative_feedback",
        "negative_shuffled_plaintext",
    )
    for index in range(GATE_NEGATIVE_COUNT):
        length = GATE_LENGTHS[index % len(GATE_LENGTHS)]
        plaintext = positive_plaintexts[index % len(positive_plaintexts)]
        if index < GATE_NEGATIVE_CLASS_COUNT:
            cipher = [negative_rng.randrange(29) for _ in range(length)]
        elif index < 2 * GATE_NEGATIVE_CLASS_COUNT:
            cipher = independent_cumulative_encrypt(plaintext)
        else:
            shuffled = list(plaintext)
            negative_rng.shuffle(shuffled)
            cipher = independent_encrypt(shuffled)
        job_id = f"gate-negative-{index + 1:03d}"
        negative_jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        labels[job_id] = negative_kinds[index // GATE_NEGATIVE_CLASS_COUNT]

    jobs = positive_jobs + negative_jobs
    if len(jobs) != GATE_POSITIVE_COUNT + GATE_NEGATIVE_COUNT:
        raise ValueError("H025 synthetic gate job count drifted")
    return jobs, answers, labels


def build_gate_public(heldout, weights):
    jobs, answers, labels = synthetic_gate(heldout, weights)
    public = dict(
        schema=1,
        hypothesis=HYPOTHESIS,
        jobs=[dict(id=job["id"], pages=job["pages"]) for job in jobs],
    )
    return public, answers, labels


def build_lp2_public(public_pages):
    return dict(
        schema=1,
        hypothesis=HYPOTHESIS,
        jobs=[dict(id="unsolved-page-reset", pages=public_pages)],
    )


def independent_job(public_job):
    pages = []
    for page in public_job["pages"]:
        decoded = independent_decode(page["cipher"])
        pages.append(
            dict(
                page=page["page"],
                rune_count=len(page["cipher"]),
                decoded_indices=decoded,
                initial_previous_plain=0,
            )
        )
    return dict(id=public_job["id"], pages=pages)


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H025 worker output fields")
    if output["status"] != "completed" or not output["read_guard_probe_passed"]:
        raise ValueError("H025 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output["jobs"]] != public_ids:
        raise ValueError("H025 worker omitted or reordered jobs")
    if answers:
        if not set(answers).issubset(public_ids):
            raise ValueError("H025 verifier answer map contains an unknown public job")
        positive_ids = {
            job_id for job_id, answer in answers.items() if answer["kind"] == "positive"
        }
        if positive_ids != EXPECTED_POSITIVE_JOB_IDS:
            raise ValueError("H025 positive answer map is incomplete or unexpected")
    else:
        positive_ids = set()

    positive_checks = []
    page_checks = 0
    rune_checks = 0
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        expected_job = independent_job(public_job)
        if output_job != expected_job:
            if output_job.get("id") != expected_job["id"]:
                raise ValueError(f"H025 job identity mismatch: {expected_job['id']}")
            raise ValueError(f"H025 independent transform mismatch: {expected_job['id']}")
        for actual_page, expected_page in zip(output_job["pages"], expected_job["pages"]):
            page_checks += 1
            rune_checks += expected_page["rune_count"]
            if public_job["id"] in positive_ids:
                answer = answers[public_job["id"]]
                if actual_page["decoded_indices"] != answer["plaintext"]:
                    raise ValueError(f"H025 positive plaintext mismatch: {public_job['id']}")
                if independent_encrypt(actual_page["decoded_indices"]) != answer["cipher"]:
                    raise ValueError(f"H025 positive roundtrip failed: {public_job['id']}")
                positive_checks.append(
                    dict(
                        job=public_job["id"],
                        page=actual_page["page"],
                        rune_count=actual_page["rune_count"],
                        score=answer["score"],
                    )
                )
    if answers and {row["job"] for row in positive_checks} != positive_ids:
        raise ValueError("H025 positive validation is incomplete")
    if answers and len(positive_checks) != len(positive_ids):
        raise ValueError("H025 positive validation contains duplicate checks")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        positive_path_checks=positive_checks,
        page_checks=page_checks,
        rune_checks=rune_checks,
        independent_algorithm="direct plaintext recurrence and cumulative-positive roundtrip",
    )


def gate_result(public, output, answers, labels, weights):
    output_map = {job["id"]: job for job in output["jobs"]}
    positives = []
    negatives = []
    for job_id, answer in answers.items():
        page = output_map[job_id]["pages"][0]
        decoded = page["decoded_indices"]
        actual_score = score(decoded, weights)
        if not math.isfinite(actual_score):
            raise ValueError(f"H025 non-finite gate score: {job_id}")
        if answer["kind"] == "positive":
            positives.append(
                dict(
                    job=job_id,
                    score=actual_score,
                    exact=decoded == answer["plaintext"],
                    pass_score=actual_score >= GATE_THRESHOLD,
                )
            )
    for job in public["jobs"]:
        job_id = job["id"]
        if job_id in answers:
            continue
        page = output_map[job_id]["pages"][0]
        actual_score = score(page["decoded_indices"], weights)
        if not math.isfinite(actual_score):
            raise ValueError(f"H025 non-finite negative score: {job_id}")
        negatives.append(
            dict(
                job=job_id,
                class_name=labels[job_id],
                score=actual_score,
                false_accept=actual_score >= GATE_THRESHOLD,
            )
        )
    positive_passes = sum(item["exact"] and item["pass_score"] for item in positives)
    negative_false_accepts = sum(item["false_accept"] for item in negatives)
    classes = sorted({item["class_name"] for item in negatives})
    return dict(
        status="passed"
        if positive_passes >= 18 and negative_false_accepts == 0
        else "failed",
        positive_requested=GATE_POSITIVE_COUNT,
        positive_exact=sum(item["exact"] for item in positives),
        positive_score_passes=positive_passes,
        negative_requested=GATE_NEGATIVE_COUNT,
        negative_false_accepts=negative_false_accepts,
        negative_class_false_accepts={
            class_name: sum(
                item["false_accept"] for item in negatives if item["class_name"] == class_name
            )
            for class_name in classes
        },
        threshold=GATE_THRESHOLD,
        positive_scores=positives,
        negative_scores=negatives,
    )


def gate_allows_lp2(gate):
    return (
        gate.get("status") == "passed"
        and gate.get("positive_score_passes") >= 18
        and gate.get("negative_false_accepts") == 0
    )


def build_gate_failure_summary(gate, verification_status):
    return dict(
        status="inconclusive",
        hypothesis=HYPOTHESIS,
        verification_status=verification_status,
        lp2_status="not_dispatched_gate_failed",
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
        statistics=None,
        interpretation="The synthetic measurement gate failed; LP2 was not dispatched to the worker.",
        negative_scope="No LP2 negative conclusion is valid when the fixed plaintext-feedback gate fails.",
        limitation="The gate failure is retained for audit; no LP2 public job was sent.",
    )


def standardize(observed, controls):
    if (
        len(observed) != 55
        or len(controls) != CONTROL_REPLICATES
        or any(len(row) != len(observed) for row in controls)
    ):
        raise ValueError("Unexpected H025 score shape")
    values_by_unit = [
        [observed[index]] + [row[index] for row in controls]
        for index in range(len(observed))
    ]
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
        public_sha256=frozen_value["lp2_public_sha256"],
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
    paths.extend(
        ROOT / name
        for name in (
            "README.md",
            "AGENTS.md",
            "STATE.md",
            "reviews/auto-cycle-008.md",
            "reviews/auto-cycle-009.md",
            "reviews/attempt-004.md",
            "reviews/feed010-operational-metaphors.md",
        )
    )
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive), bytes=archive.stat().st_size)


def _execute_worker(public, run, prefix, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"H025 deadline expired before {prefix} worker")
    execution = execute(
        [sys.executable, "-I", "-S", str(WORKER_PATH)],
        cwd=ROOT,
        timeout=remaining,
        stdin=json.dumps(public),
    )
    write_json(run / f"worker-{prefix}-execution.json", execution)
    (run / f"worker-{prefix}-stdout.json").write_text(execution["stdout"], encoding="utf8")
    (run / f"worker-{prefix}-stderr.txt").write_text(execution["stderr"], encoding="utf8")
    if execution["status"] == "timeout":
        raise TimeoutError(f"H025 {prefix} worker timed out")
    if execution["status"] != "completed":
        raise RuntimeError(f"H025 {prefix} worker failed; see worker-{prefix}-execution.json")
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
    record = dict(
        schema=1,
        attempt="auto-cycle R014",
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
            raise ValueError("H025 specification is not preregistered")
        public_pages, metadata = load_pages()
        training, training_counts, weights = scorer_basis()
        heldout = encode_text(HELDOUT_PATH.read_text(encoding="utf8"))
        gate_public, answers, labels = build_gate_public(heldout, weights)
        source_paths = [
            SPEC_PATH.relative_to(ROOT).as_posix(),
            H017_SPEC_PATH.relative_to(ROOT).as_posix(),
            H009_SPEC_PATH.relative_to(ROOT).as_posix(),
            H023_SPEC_PATH.relative_to(ROOT).as_posix(),
            CORPUS_PATH.relative_to(ROOT).as_posix(),
            TRAIN_PATH.relative_to(ROOT).as_posix(),
            HELDOUT_PATH.relative_to(ROOT).as_posix(),
            R013_REVIEW_PATH.relative_to(ROOT).as_posix(),
            R014_REVIEW_PATH.relative_to(ROOT).as_posix(),
        ]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        page_order = [page["page"] for page in public_pages]
        write_json(
            run / "inputs.json",
            dict(
                schema=1,
                derived_at_utc=started_at.isoformat(),
                corpus_version="attempt1-corpus-v1",
                pages=metadata,
                gate_public_job_ids=[job["id"] for job in gate_public["jobs"]],
                public_sha256=stable_digest(gate_public),
                job_labels=labels,
            ),
        )
        write_json(run / "public-gate.json", gate_public)
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
                training_path=TRAIN_PATH.relative_to(ROOT).as_posix(),
                training_sha256=sha256(TRAIN_PATH),
                training_rune_count=len(training),
                training_bigram_counts=training_counts,
                scorer_weights=weights,
                score_is_bigram=True,
                gate=dict(
                    positive_count=GATE_POSITIVE_COUNT,
                    negative_count=GATE_NEGATIVE_COUNT,
                    negative_class_count=GATE_NEGATIVE_CLASS_COUNT,
                    threshold=GATE_THRESHOLD,
                    lengths=list(GATE_LENGTHS),
                    positive_seed=GATE_POSITIVE_SEED,
                    negative_seed=GATE_NEGATIVE_SEED,
                ),
                control_replicates=CONTROL_REPLICATES,
                control_seed=CONTROL_SEED,
                alpha=ALPHA,
                tie_tolerance=TIE_TOLERANCE,
                total_wall_seconds=WALL_SECONDS,
                checkpoint_every=CHECKPOINT_EVERY,
                gate_public_sha256=stable_digest(gate_public),
                expected_answers_sha256=sha256(run / "verifier-only" / "answers.json"),
            ),
        )
        record.update(
            execution_started=True,
            source_files_verified=source_count,
            frozen_sha256=sha256(frozen),
        )
        write_json(run / "record.json", record)

        gate_output = _execute_worker(gate_public, run, "gate", deadline)
        gate_verification = verify_worker(gate_public, gate_output, answers)
        write_json(run / "independent-verification-gate.json", gate_verification)
        gate = gate_result(gate_public, gate_output, answers, labels, weights)
        write_json(run / "power-gate.json", gate)
        if not gate_allows_lp2(gate):
            if time.monotonic() >= deadline:
                raise TimeoutError("H025 wall budget exceeded after failed power gate")
            summary = build_gate_failure_summary(gate, gate_verification["status"])
            write_json(run / "statistics.json", summary)
            write_json(
                run / "lp2-skipped.json",
                dict(
                    status="skipped",
                    reason="power_gate_failed",
                    gate_worker_pages=gate_verification["page_checks"],
                    lp2_dispatched=False,
                    power_gate_sha256=sha256(run / "power-gate.json"),
                ),
            )
            record.update(
                status="inconclusive",
                result=dict(gate_status=gate["status"], lp2_dispatched=False),
                actual_coverage=summary["coverage"],
                unsolved_page_candidates=[],
            )
            raise GateFailure("H025 power gate failed; LP2 was not dispatched")

        if time.monotonic() >= deadline:
            raise TimeoutError("H025 wall budget exceeded before LP2 dispatch")
        lp2_public = build_lp2_public(public_pages)
        write_json(run / "public-lp2.json", lp2_public)
        frozen_lp2 = run / "frozen-lp2.json"
        frozen_data = json.loads(frozen.read_text(encoding="utf8"))
        frozen_data.update(
            lp2_public_sha256=stable_digest(lp2_public),
            lp2_job_id="unsolved-page-reset",
            lp2_dispatch_after_gate=True,
            parent_frozen_sha256=sha256(frozen),
        )
        write_json(frozen_lp2, frozen_data)
        lp2_output = _execute_worker(lp2_public, run, "lp2", deadline)
        lp2_verification = verify_worker(lp2_public, lp2_output, {})
        write_json(run / "independent-verification-lp2.json", lp2_verification)
        if gate_verification["status"] != "passed" or lp2_verification["status"] != "passed":
            raise ValueError("H025 independent verification did not pass")

        observed_job = lp2_output["jobs"][0]
        observed_rows = []
        for page in observed_job["pages"]:
            decoded = page["decoded_indices"]
            observed_rows.append(
                dict(
                    page=page["page"],
                    rune_count=page["rune_count"],
                    decoded_indices=decoded,
                    score=score(decoded, weights),
                )
            )
        if [row["page"] for row in observed_rows] != page_order:
            raise ValueError("Observed H025 page order changed")
        if any(row["score"] is None or not math.isfinite(row["score"]) for row in observed_rows):
            raise ValueError("H025 observed score is missing or non-finite")
        observed = [row["score"] for row in observed_rows]
        write_json(
            run / "decoded.json",
            dict(
                algorithm="P[-1]=0; P[i]=(C[i]-P[i-1]) mod29",
                scorer="training-only adjacent bigram log weight",
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
                raise TimeoutError(f"H025 wall budget exceeded after {len(controls)} controls")
            shuffled_pages = []
            for page in public_pages:
                cipher = list(page["cipher"])
                rng.shuffle(cipher)
                shuffled_pages.append(dict(page=page["page"], cipher=cipher))
            control_output = independent_job(
                dict(id="control", pages=shuffled_pages)
            )
            metrics = [
                score(row["decoded_indices"], weights)
                for row in control_output["pages"]
            ]
            if any(value is None or not math.isfinite(value) for value in metrics):
                raise ValueError("Non-finite H025 control score")
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
                    frozen=frozen_lp2,
                    rng=rng,
                    status="complete" if replicate == CONTROL_REPLICATES else "partial",
                )
                write_json(run / "record.json", record)
        if time.monotonic() >= deadline:
            raise TimeoutError("H025 wall budget exceeded after final control")
        write_json(
            run / "control-scores.json",
            dict(
                schema=1,
                algorithm="within-page full ciphertext permutation",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=page_order,
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
            status = "zero_variance" if std == 0 else (
                "lead" if p <= ALPHA else "not_detected"
            )
            stat_rows.append(
                dict(
                    page=page,
                    score=metric,
                    statistic_status=status,
                    candidate=status == "lead",
                    z=z,
                    p_adjusted=p,
                )
            )
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        strongest = sorted(
            stat_rows,
            key=lambda row: (row["p_adjusted"], -row["z"], row["page"]),
        )[:10]
        summary = dict(
            status="inconclusive" if leads else "negative",
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
            interpretation="The fixed plaintext-feedback recurrence is a structural language-score diagnostic; it does not decode a verified LP2 plaintext or identify a key.",
            negative_scope="Only H025's page-reset P[-1]=0 recurrence, all-transition training-only bigram score and full within-page ciphertext-permutation null.",
            limitation="No independent LP2 plaintext or image-level glyph audit is available; LP2/50 literal grid is unexecuted.",
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("H025 wall budget exceeded before statistics finalization")
        write_json(run / "statistics.json", summary)
        if time.monotonic() >= deadline:
            summary["status"] = "timeout"
            summary["scientific_result_valid"] = False
            summary["limitation"] += " Final statistics write crossed the monotonic deadline."
            write_json(run / "statistics.json", summary)
            raise TimeoutError("H025 wall budget exceeded during statistics finalization")
        record.update(
            status=summary["status"],
            result=dict(
                leads=len(leads),
                gate_status=gate["status"],
                lp2_dispatched=True,
                strongest=strongest[:3],
            ),
            actual_coverage=summary["coverage"],
            unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"],
        )
        if code_snapshot(ROOT) != snapshot or any(
            sha256(ROOT / path) != value for path, value in source_hashes.items()
        ):
            raise ValueError("Frozen H025 code or source input changed during execution")
        verify_sources(ROOT)
    except Exception as exc:
        if isinstance(exc, GateFailure):
            record.update(status="inconclusive", gate_failure=str(exc))
        else:
            record.update(
                status="timeout" if isinstance(exc, TimeoutError) else "error",
                error=repr(exc),
            )
            (run / "exception.stderr.txt").write_text(
                traceback.format_exc(), encoding="utf8"
            )
    record.update(
        finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        elapsed_seconds=time.monotonic() - stopwatch,
    )
    write_json(run / "record.json", record)
    try:
        record["reproduction_bundle"] = archive_run(run, snapshot)
    except Exception as exc:
        record.update(status="error", error=f"ArchiveError: {exc!r}")
        (run / "archive-exception.stderr.txt").write_text(
            traceback.format_exc(), encoding="utf8"
        )
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
