"""Run H016: a fixed periodic key with a finite plaintext-F exception state."""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import platform
import random
import re
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


SPEC_PATH = ROOT / "hypotheses/H016-periodic-plaintext-F-state-v1.json"
H014_SPEC_PATH = ROOT / "hypotheses/H014-circumference-transfer-v1.json"
KEY_SOURCE_PATH = ROOT / "sources/context/known-keys.txt"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
WORKER_PATH = ROOT / "scripts/attempt12_worker.py"
KEY = (0, 10, 4, 0, 1, 19, 0, 18, 4, 18, 9, 0, 18)
BRANCHES = ("continuous", "page_reset")
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011601
SYNTHETIC_SEED = 33011602
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120

SUMMARY_FIELDS = (
    "initial_phases",
    "rune_count",
    "input_zero_runes",
    "state_counts",
    "max_state_count",
    "final_phases",
    "final_state_count",
    "terminal_path_count_capped",
    "unique_terminal_path",
    "ordinary_edges",
    "exception_edges",
    "total_edges",
    "first_dead_position",
    "legal_prefix_length",
    "legal_prefix_ratio",
    "state_digest",
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )


def stable_digest(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def load_key_basis():
    context = KEY_SOURCE_PATH.read_text(encoding="utf8")
    match = re.search(r"firfumferenfe\s*\(([^)]+)\)", context, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Public FIRFUMFERENFE key source line is missing")
    source_key = tuple(int(value.strip()) for value in match.group(1).split(","))
    if source_key != KEY:
        raise ValueError("Public key source differs from H016 frozen key")
    h014 = json.loads(H014_SPEC_PATH.read_text(encoding="utf8"))
    if "FIRFUMFERENFE" not in json.dumps(h014, ensure_ascii=False):
        raise ValueError("H014 source basis no longer names FIRFUMFERENFE")
    return dict(
        key_label="FIRFUMFERENFE",
        key_indices=list(source_key),
        key_source_sha256=sha256(KEY_SOURCE_PATH),
        h014_spec_sha256=sha256(H014_SPEC_PATH),
    )


def load_corpus():
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


def independent_scan(cipher, starts, key=KEY):
    """Set recurrence independent of the guarded worker implementation."""
    if any(type(value) is not int or not 0 <= value < 29 for value in cipher):
        raise ValueError("Cipher outside rune domain")
    starts = tuple(starts)
    if len(set(starts)) != len(starts) or any(
        type(value) is not int or not 0 <= value < len(key) for value in starts
    ):
        raise ValueError("Invalid independent start phases")
    states = set(starts)
    ways = {phase: 1 for phase in starts}
    history = [sum(1 << phase for phase in states)]
    state_counts = [len(states)]
    ordinary_edges = 0
    exception_edges = 0
    first_dead_position = None
    for position, cipher_value in enumerate(cipher):
        next_states = set()
        next_ways = {}
        for phase, count in ways.items():
            delta = key[phase]
            if cipher_value == 0:
                exception_edges += 1
                next_states.add(phase)
                next_ways[phase] = min(2, next_ways.get(phase, 0) + count)
                if delta != 0:
                    next_phase = (phase + 1) % len(key)
                    ordinary_edges += 1
                    next_states.add(next_phase)
                    next_ways[next_phase] = min(
                        2, next_ways.get(next_phase, 0) + count
                    )
            elif cipher_value != delta:
                next_phase = (phase + 1) % len(key)
                ordinary_edges += 1
                next_states.add(next_phase)
                next_ways[next_phase] = min(
                    2, next_ways.get(next_phase, 0) + count
                )
        states = next_states
        ways = next_ways
        history.append(sum(1 << phase for phase in states))
        state_counts.append(len(states))
        if not states and first_dead_position is None:
            first_dead_position = position
    legal_prefix_length = (
        len(cipher) if first_dead_position is None else first_dead_position
    )
    legal_prefix_ratio = legal_prefix_length / len(cipher) if cipher else 1.0
    terminal_paths = min(2, sum(ways.values()))
    digest = hashlib.sha256()
    for mask in history:
        digest.update(mask.to_bytes(2, "little"))
    return {
        "initial_phases": sorted(starts),
        "rune_count": len(cipher),
        "input_zero_runes": sum(value == 0 for value in cipher),
        "state_counts": state_counts,
        "max_state_count": max(state_counts, default=0),
        "final_phases": sorted(ways),
        "final_state_count": len(ways),
        "terminal_path_count_capped": terminal_paths,
        "unique_terminal_path": len(ways) == 1 and terminal_paths == 1,
        "ordinary_edges": ordinary_edges,
        "exception_edges": exception_edges,
        "total_edges": ordinary_edges + exception_edges,
        "first_dead_position": first_dead_position,
        "legal_prefix_length": legal_prefix_length,
        "legal_prefix_ratio": legal_prefix_ratio,
        "state_digest": digest.hexdigest(),
    }


def independent_job(job):
    states = (0,)
    rows = []
    for page in job["pages"]:
        starts = states if job["branch"] == "continuous" else (0,)
        row = independent_scan(page["cipher"], starts)
        row["page"] = page["page"]
        rows.append(row)
        if job["branch"] == "continuous":
            states = tuple(row["final_phases"])
    return {
        "id": job["id"],
        "branch": job["branch"],
        "pages": rows,
        "final_phases": sorted(states) if job["branch"] == "continuous" else None,
    }


def encrypt_plain(plaintext, key=KEY):
    cipher = []
    phase = 0
    trace = []
    for position, value in enumerate(plaintext):
        if type(value) is not int or not 0 <= value < 29:
            raise ValueError("Synthetic plaintext outside rune domain")
        phase_before = phase
        if value == 0:
            cipher.append(0)
            trace.append(
                dict(
                    position=position,
                    plaintext=value,
                    ciphertext=0,
                    phase_before=phase_before,
                    phase_after=phase,
                    kind="plaintext_f_exception",
                )
            )
            continue
        ciphertext = (value + key[phase]) % 29
        phase = (phase + 1) % len(key)
        trace.append(
            dict(
                position=position,
                plaintext=value,
                ciphertext=ciphertext,
                phase_before=phase_before,
                phase_after=phase,
                kind="ordinary_ciphertext_f" if ciphertext == 0 else "ordinary",
            )
        )
        cipher.append(ciphertext)
    return cipher, phase, trace


def synthetic_controls(heldout):
    if len(heldout) < 256:
        raise ValueError("Heldout text is too short for H016 synthetic controls")
    plans = [list(heldout[:128])]
    plans[0][0] = 0
    plans[0][1] = 1
    plans[0][2] = (-KEY[1]) % 29
    rng = random.Random(SYNTHETIC_SEED)
    random_plain = [rng.randrange(29) for _ in range(128)]
    random_plain[0] = 0
    random_plain[1] = 1
    random_plain[2] = (-KEY[1]) % 29
    random_plain[17] = 0
    random_plain[64] = 0
    plans.append(random_plain)

    jobs = []
    answers = {}
    for index, plaintext in enumerate(plans):
        job_name = f"synthetic-positive-{index + 1}"
        cipher, terminal, trace = encrypt_plain(plaintext)
        answers[job_name] = dict(
            kind="positive",
            plaintext=plaintext,
            expected_terminal_phase=terminal,
            trace=trace,
            exception_positions=[
                row["position"] for row in trace if row["kind"] == "plaintext_f_exception"
            ],
            ordinary_ciphertext_f_positions=[
                row["position"] for row in trace if row["kind"] == "ordinary_ciphertext_f"
            ],
        )
        for branch in BRANCHES:
            jobs.append(
                dict(
                    id=f"{job_name}-{branch}",
                    branch=branch,
                    pages=[dict(page=job_name, cipher=cipher)],
                )
            )
    impossible = dict(id="incompatible", branch="page_reset", pages=[dict(page="incompatible", cipher=[1, KEY[1]])])
    jobs.append(impossible)
    answers["incompatible"] = dict(kind="incompatible")
    return jobs, answers


def make_public_and_answers(public_pages, heldout):
    jobs = []
    for branch in BRANCHES:
        jobs.append(
            dict(id=f"unsolved-{branch}", branch=branch, pages=public_pages)
        )
    synthetic_jobs, answers = synthetic_controls(heldout)
    jobs.extend(synthetic_jobs)
    return dict(schema=1, hypothesis="H016-periodic-plaintext-F-state-v1", jobs=jobs), answers


def randomize_preserving_zero_positions(values, rng):
    """Shuffle only nonzero values while preserving every ciphertext-F position."""
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
        raise ValueError("Zero-preserving shuffle did not consume its nonzero multiset")
    return result


def replay_expected(cipher, plaintext):
    if len(cipher) != len(plaintext):
        raise ValueError("Synthetic expected path length mismatch")
    phase = 0
    for position, (cipher_value, plain_value) in enumerate(zip(cipher, plaintext)):
        if plain_value == 0:
            if cipher_value != 0:
                raise ValueError(f"Expected plaintext-F path mismatch at {position}")
        else:
            expected = (plain_value + KEY[phase]) % 29
            if cipher_value != expected:
                raise ValueError(f"Expected ordinary path mismatch at {position}")
            phase = (phase + 1) % len(KEY)
    return phase


def verify_worker(public, output, answers):
    if not output.get("read_guard_probe_passed"):
        raise ValueError("H016 worker read isolation probe failed")
    if [job["id"] for job in output.get("jobs", [])] != [job["id"] for job in public["jobs"]]:
        raise ValueError("H016 worker omitted or reordered jobs")
    path_checks = []
    impossible_checks = []
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job.get("id") != public_job["id"] or output_job.get("branch") != public_job["branch"]:
            raise ValueError("H016 worker job identity mismatch")
        expected = independent_job(public_job)
        if [row["page"] for row in output_job["pages"]] != [row["page"] for row in expected["pages"]]:
            raise ValueError("H016 worker page coverage mismatch")
        for actual, expected_row in zip(output_job["pages"], expected["pages"]):
            if any(actual.get(field) != expected_row[field] for field in SUMMARY_FIELDS):
                raise ValueError(f"Independent H016 state check failed: {public_job['id']}/{actual['page']}")
        if output_job.get("final_phases") != expected["final_phases"]:
            raise ValueError(f"H016 worker final phase mismatch: {public_job['id']}")
        if public_job["id"] in answers and answers[public_job["id"]].get("kind") == "positive":
            answer_name = public_job["id"].rsplit("-", 1)[0]
            answer = answers[answer_name]
            page = public_job["pages"][0]
            endpoint = replay_expected(page["cipher"], answer["plaintext"])
            row = output_job["pages"][0]
            if endpoint not in row["final_phases"]:
                raise ValueError(f"H016 private positive path is unreachable: {public_job['id']}")
            if endpoint != answer["expected_terminal_phase"]:
                raise ValueError("H016 synthetic endpoint changed")
            path_checks.append(dict(job=public_job["id"], endpoint_phase=endpoint))
        if public_job["id"] == "incompatible":
            row = output_job["pages"][0]
            if row["final_state_count"] != 0:
                raise ValueError("H016 incompatible control remained reachable")
            impossible_checks.append(dict(job=public_job["id"], status="negative"))
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        public_sha256=stable_digest(public),
        positive_path_checks=path_checks,
        incompatible_checks=impossible_checks,
        independent_algorithm="separate set recurrence with modulo-13 phase and capped path multiplicity",
    )


def continuous_ratio(rows, page_lengths):
    total = sum(page_lengths)
    completed = 0
    for row, length in zip(rows, page_lengths):
        if not row["initial_phases"]:
            break
        completed += row["legal_prefix_length"]
        if row["final_state_count"] == 0:
            break
        if row["legal_prefix_length"] != length:
            break
    return completed / total if total else 1.0


def metric_vector_from_observed(public, output, page_order, page_lengths):
    output_map = {job["id"]: job for job in output["jobs"]}
    reset_job = output_map["unsolved-page_reset"]
    continuous_job = output_map["unsolved-continuous"]
    if [row["page"] for row in reset_job["pages"]] != page_order:
        raise ValueError("Observed page-reset metric order changed")
    values = [row["legal_prefix_ratio"] for row in reset_job["pages"]]
    values.append(continuous_ratio(continuous_job["pages"], page_lengths))
    return values


def metric_vector_from_pages(pages):
    states = (0,)
    reset_values = []
    continuous_rows = []
    for page in pages:
        reset_row = independent_scan(page["cipher"], (0,))
        reset_values.append(reset_row["legal_prefix_ratio"])
        continuous_row = independent_scan(page["cipher"], states)
        continuous_rows.append(continuous_row)
        states = tuple(continuous_row["final_phases"])
    reset_values.append(continuous_ratio(continuous_rows, [len(page["cipher"]) for page in pages]))
    return reset_values


def standardize(observed, controls):
    if len(observed) != 56 or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected H016 metric shape")
    if any(len(row) != len(observed) for row in controls):
        raise ValueError("H016 control metric width mismatch")
    means, stds = [], []
    for index in range(len(observed)):
        values = [observed[index]] + [row[index] for row in controls]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        stds.append(variance ** 0.5)
    observed_z = [
        (value - mean) / std if std > 0 else 0.0
        for value, mean, std in zip(observed, means, stds)
    ]
    control_max = []
    for row in controls:
        control_max.append(
            max(
                (value - mean) / std if std > 0 else 0.0
                for value, mean, std in zip(row, means, stds)
            )
        )
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


def archive_run(run, snapshot):
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / path for path in snapshot["files"]]
    paths.extend(
        path
        for directory in ("sources", "data", "hypotheses", "research")
        for path in (ROOT / directory).rglob("*")
        if path.is_file()
    )
    paths.extend(
        path for path in run.rglob("*") if path.is_file() and path != archive
    )
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
    snapshot = code_snapshot(ROOT)
    record = dict(
        schema=1,
        attempt="auto-cycle R008",
        hypothesis="H016-periodic-plaintext-F-state-v1",
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
        key_basis = load_key_basis()
        corpus_pages, public_pages, metadata = load_corpus()
        heldout = encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))
        public, answers = make_public_and_answers(public_pages, heldout)
        source_paths = [
            SPEC_PATH.relative_to(ROOT).as_posix(),
            H014_SPEC_PATH.relative_to(ROOT).as_posix(),
            KEY_SOURCE_PATH.relative_to(ROOT).as_posix(),
            CORPUS_PATH.relative_to(ROOT).as_posix(),
        ]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        page_order = [page["page"] for page in public_pages]
        page_lengths = [len(page["cipher"]) for page in public_pages]
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
        frozen = dict(
            schema=1,
            frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            specification=spec,
            source_hashes=source_hashes,
            code_version=snapshot,
            key_basis=key_basis,
            page_order=page_order,
            page_lengths=page_lengths,
            applicable_pages=page_order,
            excluded_pages=["LP2/50"],
            rune_count=sum(page_lengths),
            branches=list(BRANCHES),
            statistic_units=56,
            control_replicates=CONTROL_REPLICATES,
            control_seed=CONTROL_SEED,
            synthetic_seed_verifier_only=SYNTHETIC_SEED,
            alpha=ALPHA,
            tie_tolerance=TIE_TOLERANCE,
            total_wall_seconds=WALL_SECONDS,
            expected_sha256=sha256(run / "verifier-only" / "answers.json"),
            public_sha256=stable_digest(public),
        )
        write_json(run / "frozen.json", frozen)
        record.update(
            execution_started=True,
            source_files_verified=source_count,
            frozen_sha256=sha256(run / "frozen.json"),
        )
        write_json(run / "record.json", record)

        execution = execute(
            [sys.executable, "-I", "-S", str(WORKER_PATH)],
            cwd=ROOT,
            timeout=WALL_SECONDS,
            stdin=json.dumps(public),
        )
        write_json(run / "worker-execution.json", execution)
        (run / "worker-stdout.json").write_text(execution["stdout"], encoding="utf8")
        (run / "worker-stderr.txt").write_text(execution["stderr"], encoding="utf8")
        if execution["status"] == "timeout":
            raise TimeoutError("H016 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H016 worker failed; see worker-execution.json")
        output = json.loads(execution["stdout"])
        write_json(run / "worker-output.json", output)
        verification = verify_worker(public, output, answers)
        write_json(run / "independent-verification.json", verification)
        observed = metric_vector_from_observed(output and public, output, page_order, page_lengths)
        write_json(
            run / "observed.json",
            dict(
                unit_order=[f"page_reset::{page}" for page in page_order] + ["continuous::LP2/0..55"],
                metrics=observed,
                metrics_sha256=stable_digest(observed),
            ),
        )

        controls = []
        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() - stopwatch > WALL_SECONDS:
                raise TimeoutError(f"H016 wall budget exceeded after {len(controls)} controls")
            shuffled_pages = []
            for page in public_pages:
                replacement = randomize_preserving_zero_positions(page["cipher"], rng)
                shuffled_pages.append(dict(page=page["page"], cipher=replacement))
            controls.append(metric_vector_from_pages(shuffled_pages))
            record["controls_completed"] = len(controls)
            if replicate in {1, 10, 100, CONTROL_REPLICATES}:
                write_json(run / "record.json", record)
        write_json(
            run / "control-metrics.json",
            dict(
                schema=1,
                algorithm="fixed-zero-mask within-page nonzero permutation",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=[f"page_reset::{page}" for page in page_order] + ["continuous::LP2/0..55"],
                metric_rows=controls,
            ),
        )
        stats = standardize(observed, controls)
        unit_order = [f"page_reset::{page}" for page in page_order] + ["continuous::LP2/0..55"]
        stat_rows = []
        for unit, metric, z, p in zip(unit_order, observed, stats["observed_z"], stats["p_adjusted"]):
            stat_rows.append(
                dict(
                    unit=unit,
                    metric=metric,
                    z=z,
                    p_adjusted=p,
                    status="inconclusive" if p <= ALPHA else "negative",
                )
            )
        leads = [row for row in stat_rows if row["status"] == "inconclusive"]
        strongest = sorted(stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["unit"]))[:10]
        summary = dict(
            status="inconclusive" if leads else "negative",
            hypothesis="H016-periodic-plaintext-F-state-v1",
            verification_status="passed",
            controls_completed=len(controls),
            coverage=dict(
                pages=55,
                applicable_pages=55,
                excluded_pages=["LP2/50"],
                runes=12956,
                branches=2,
                statistic_units=56,
                control_replicates=len(controls),
                unsolved_page_candidates=[row["unit"] for row in leads],
            ),
            leads=leads,
            strongest=strongest,
            statistics=stats,
            state_result="Reachable states are compatibility evidence; no plaintext path was selected or emitted.",
            negative_scope="Only H016's fixed FIRFUMFERENFE key, subtractive direction, modulo-13 phase, copied plaintext-F exception, two continuity branches and fixed-zero-mask permutation null.",
            limitation="No independent LP2 plaintext or image-level glyph audit is available; LP2/50 literal grid is unexecuted.",
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
            raise ValueError("Frozen H016 code or source input changed during execution")
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
