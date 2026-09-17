"""Run H016-v2: periodic FIRFUMFERENFE with explicit F-state ambiguity.

This runner keeps model reachability, statistical evidence and execution
status separate.  The guarded worker sees only the public ciphertext jobs;
private synthetic paths stay in the verifier-only directory.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import os
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
from lp_lab.periodic_f_state_v2 import DEFAULT_KEY, PATH_CAP
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import indices
from lp_lab.synthetic import encode_text


SPEC_PATH = ROOT / "hypotheses/H016-periodic-plaintext-F-state-v2.json"
H014_SPEC_PATH = ROOT / "hypotheses/H014-circumference-transfer-v1.json"
KEY_SOURCE_PATH = ROOT / "sources/context/known-keys.txt"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
WORKER_PATH = ROOT / "scripts/attempt13_worker_v2.py"
KEY = DEFAULT_KEY
BRANCHES = ("continuous", "page_reset")
HYPOTHESIS = "H016-periodic-plaintext-F-state-v2"
CONTROL_REPLICATES = 999
CONTROL_SEED = 33011601
SYNTHETIC_SEED = 33011602
ALPHA = 0.01
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 120
CHECKPOINT_EVERY = 25

EXPECTED_POSITIVE_JOB_IDS = frozenset(
    {
        "synthetic-positive-1-continuous",
        "synthetic-positive-1-page_reset",
        "synthetic-positive-2-continuous",
        "synthetic-positive-2-page_reset",
    }
)
IMPOSSIBLE_JOB_ID = "incompatible-control-v2"

SUMMARY_FIELDS = (
    "initial_phases",
    "initial_path_counts",
    "rune_count",
    "input_zero_runes",
    "state_counts",
    "max_state_count",
    "final_phases",
    "final_path_counts",
    "final_state_count",
    "terminal_path_count_capped",
    "unique_terminal_path",
    "ordinary_edges",
    "exception_edges",
    "total_edges",
    "first_dead_position",
    "legal_prefix_length",
    "legal_prefix_ratio",
    "model_status",
    "state_digest",
    "upstream_dead_page",
    "not_reached_reason",
)


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


def load_key_basis():
    context = KEY_SOURCE_PATH.read_text(encoding="utf8")
    match = re.search(r"firfumferenfe\s*\(([^)]+)\)", context, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Public FIRFUMFERENFE key source line is missing")
    source_key = tuple(int(value.strip()) for value in match.group(1).split(","))
    if source_key != KEY:
        raise ValueError("Public key source differs from H016-v2 frozen key")
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


def _validate_key(key):
    key = tuple(key)
    if not key or any(type(value) is not int or not 0 <= value < 29 for value in key):
        raise ValueError("Invalid direct-table key")
    return key


def direct_transition_table(key=KEY):
    """Build ciphertext transitions by forward-enumerating every plaintext.

    This is intentionally independent of the worker's inverse branch code.
    The table contains all 13x29 phase/ciphertext cells, including empty
    cells and the phase-12 wrap.
    """
    key = _validate_key(key)
    table = {}
    period = len(key)
    for phase, delta in enumerate(key):
        for cipher_value in range(29):
            table[(phase, cipher_value)] = []
        for plaintext in range(29):
            if plaintext == 0:
                cipher_value = 0
                next_phase = phase
                kind = "exception"
            else:
                cipher_value = (plaintext + delta) % 29
                next_phase = (phase + 1) % period
                kind = "ordinary"
            edge = (next_phase, kind)
            if edge not in table[(phase, cipher_value)]:
                table[(phase, cipher_value)].append(edge)
        for cipher_value in range(29):
            table[(phase, cipher_value)] = tuple(table[(phase, cipher_value)])
    return table


def _validate_starts(starts, initial_ways, key_length):
    starts = tuple(starts)
    if len(set(starts)) != len(starts) or any(
        type(value) is not int or not 0 <= value < key_length for value in starts
    ):
        raise ValueError("Invalid independent start phases")
    if initial_ways is None:
        ways = {phase: 1 for phase in starts}
    else:
        if set(initial_ways) != set(starts):
            raise ValueError("Independent counts do not match start phases")
        ways = {}
        for phase in starts:
            count = initial_ways[phase]
            if type(count) is not int or not 1 <= count <= PATH_CAP:
                raise ValueError("Independent counts must be capped positive integers")
            ways[phase] = count
    return starts, ways


def _count_list(counts):
    return [[phase, counts[phase]] for phase in sorted(counts)]


def independent_scan(cipher, starts, key=KEY, initial_ways=None):
    """Recompute summaries through the independently-built direct table."""
    key = _validate_key(key)
    if any(type(value) is not int or not 0 <= value < 29 for value in cipher):
        raise ValueError("Cipher outside rune domain")
    starts, ways = _validate_starts(starts, initial_ways, len(key))
    initial_counts = dict(ways)
    table = direct_transition_table(key)
    states = set(starts)
    history = [sum(1 << phase for phase in states)]
    state_counts = [len(states)]
    ordinary_edges = 0
    exception_edges = 0
    first_dead_position = None
    for position, cipher_value in enumerate(cipher):
        next_ways = {}
        for phase in states:
            for next_phase, kind in table[(phase, cipher_value)]:
                if kind == "ordinary":
                    ordinary_edges += 1
                else:
                    exception_edges += 1
                next_ways[next_phase] = min(
                    PATH_CAP, next_ways.get(next_phase, 0) + ways[phase]
                )
        states = set(next_ways)
        ways = next_ways
        history.append(sum(1 << phase for phase in states))
        state_counts.append(len(states))
        if not states and first_dead_position is None:
            first_dead_position = position
    if not starts:
        legal_prefix_length = None
        legal_prefix_ratio = None
    else:
        legal_prefix_length = (
            len(cipher) if first_dead_position is None else first_dead_position
        )
        legal_prefix_ratio = legal_prefix_length / len(cipher) if cipher else 1.0
    terminal_paths = min(PATH_CAP, sum(ways.values()))
    return {
        "initial_phases": sorted(starts),
        "initial_path_counts": _count_list(initial_counts),
        "rune_count": len(cipher),
        "input_zero_runes": sum(value == 0 for value in cipher),
        "state_counts": state_counts,
        "max_state_count": max(state_counts, default=0),
        "final_phases": sorted(ways),
        "final_path_counts": _count_list(ways),
        "final_state_count": len(ways),
        "terminal_path_count_capped": terminal_paths,
        "unique_terminal_path": len(ways) == 1 and terminal_paths == 1,
        "ordinary_edges": ordinary_edges,
        "exception_edges": exception_edges,
        "total_edges": ordinary_edges + exception_edges,
        "first_dead_position": first_dead_position,
        "legal_prefix_length": legal_prefix_length,
        "legal_prefix_ratio": legal_prefix_ratio,
        "model_status": "compatible" if states else ("not_reached" if not starts else "dead"),
        "state_digest": hashlib.sha256(
            b"".join(mask.to_bytes(2, "little") for mask in history)
        ).hexdigest(),
    }


def _not_reached_row(cipher, page, upstream_dead_page):
    row = independent_scan(cipher, (), KEY, initial_ways={})
    row.update(
        page=page,
        model_status="not_reached",
        upstream_dead_page=upstream_dead_page,
        not_reached_reason="continuous_prefix_state_empty",
        first_dead_position=None,
        legal_prefix_length=None,
        legal_prefix_ratio=None,
    )
    return row


def independent_job(job):
    states = (0,)
    ways = {0: 1}
    rows = []
    upstream_dead_page = None
    for page in job["pages"]:
        if job["branch"] == "continuous" and not states:
            rows.append(_not_reached_row(page["cipher"], page["page"], upstream_dead_page))
            continue
        starts = states if job["branch"] == "continuous" else (0,)
        initial_ways = ways if job["branch"] == "continuous" else {0: 1}
        row = independent_scan(page["cipher"], starts, KEY, initial_ways)
        row.update(
            page=page["page"],
            model_status="compatible" if row["final_state_count"] else "dead",
            upstream_dead_page=None,
            not_reached_reason=None,
        )
        rows.append(row)
        if job["branch"] == "continuous":
            states = tuple(row["final_phases"])
            ways = {phase: count for phase, count in row["final_path_counts"]}
            if not states:
                upstream_dead_page = page["page"]
    return {
        "id": job["id"],
        "branch": job["branch"],
        "pages": rows,
        "final_phases": sorted(states) if job["branch"] == "continuous" else None,
        "final_path_counts": (
            _count_list(ways) if job["branch"] == "continuous" else None
        ),
    }


def encrypt_plain(plaintext, key=KEY):
    cipher = []
    phase = 0
    trace = []
    key = _validate_key(key)
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
        raise ValueError("Heldout text is too short for H016-v2 synthetic controls")
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
        base_name = f"synthetic-positive-{index + 1}"
        cipher, terminal, trace = encrypt_plain(plaintext)
        for branch in BRANCHES:
            job_id = f"{base_name}-{branch}"
            jobs.append(
                dict(
                    id=job_id,
                    branch=branch,
                    pages=[dict(page=base_name, cipher=cipher)],
                )
            )
            # The verifier map intentionally uses the complete public job ID.
            answers[job_id] = dict(
                kind="positive",
                branch=branch,
                plaintext=plaintext,
                expected_terminal_phase=terminal,
                trace=trace,
                exception_positions=[
                    row["position"]
                    for row in trace
                    if row["kind"] == "plaintext_f_exception"
                ],
                ordinary_ciphertext_f_positions=[
                    row["position"]
                    for row in trace
                    if row["kind"] == "ordinary_ciphertext_f"
                ],
            )
    jobs.append(
        dict(
            id=IMPOSSIBLE_JOB_ID,
            branch="page_reset",
            pages=[dict(page=IMPOSSIBLE_JOB_ID, cipher=[1, KEY[1]])],
        )
    )
    answers[IMPOSSIBLE_JOB_ID] = dict(kind="incompatible")
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS | {IMPOSSIBLE_JOB_ID}:
        raise ValueError("Synthetic answer/job registration drifted")
    return jobs, answers


def make_public_and_answers(public_pages, heldout):
    jobs = [
        dict(id=f"unsolved-{branch}", branch=branch, pages=public_pages)
        for branch in BRANCHES
    ]
    synthetic_jobs, answers = synthetic_controls(heldout)
    jobs.extend(synthetic_jobs)
    return dict(schema=1, hypothesis=HYPOTHESIS, jobs=jobs), answers


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
        raise ValueError("Zero-preserving shuffle did not consume its nonzero multiset")
    return result


def replay_expected(cipher, plaintext, key=KEY):
    if len(cipher) != len(plaintext):
        raise ValueError("Synthetic expected path length mismatch")
    key = _validate_key(key)
    phase = 0
    for position, (cipher_value, plain_value) in enumerate(zip(cipher, plaintext)):
        if plain_value == 0:
            if cipher_value != 0:
                raise ValueError(f"Expected plaintext-F path mismatch at {position}")
        else:
            expected = (plain_value + key[phase]) % 29
            if cipher_value != expected:
                raise ValueError(f"Expected ordinary path mismatch at {position}")
            phase = (phase + 1) % len(key)
    return phase


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H016-v2 worker output fields")
    if output["status"] != "completed" or not output.get("read_guard_probe_passed"):
        raise ValueError("H016-v2 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output.get("jobs", [])] != public_ids:
        raise ValueError("H016-v2 worker omitted or reordered jobs")
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS | {IMPOSSIBLE_JOB_ID}:
        raise ValueError("Private answer map is incomplete or contains unexpected jobs")

    path_checks = []
    impossible_checks = []
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        job_id = public_job["id"]
        if output_job.get("id") != job_id or output_job.get("branch") != public_job["branch"]:
            raise ValueError("H016-v2 worker job identity mismatch")
        expected = independent_job(public_job)
        if [row["page"] for row in output_job["pages"]] != [
            row["page"] for row in expected["pages"]
        ]:
            raise ValueError(f"H016-v2 worker page coverage mismatch: {job_id}")
        for actual, expected_row in zip(output_job["pages"], expected["pages"]):
            if any(actual.get(field) != expected_row[field] for field in SUMMARY_FIELDS):
                raise ValueError(f"Independent H016-v2 state check failed: {job_id}/{actual['page']}")
        if output_job.get("final_phases") != expected["final_phases"]:
            raise ValueError(f"H016-v2 worker final phase mismatch: {job_id}")
        if output_job.get("final_path_counts") != expected["final_path_counts"]:
            raise ValueError(f"H016-v2 worker final path-count mismatch: {job_id}")

        if answers.get(job_id, {}).get("kind") == "positive":
            answer = answers[job_id]
            if answer["branch"] != public_job["branch"]:
                raise ValueError(f"H016-v2 positive branch mismatch: {job_id}")
            page = public_job["pages"][0]
            endpoint = replay_expected(page["cipher"], answer["plaintext"])
            row = output_job["pages"][0]
            if endpoint not in row["final_phases"]:
                raise ValueError(f"H016-v2 private positive path is unreachable: {job_id}")
            if endpoint != answer["expected_terminal_phase"]:
                raise ValueError(f"H016-v2 synthetic endpoint changed: {job_id}")
            if row["terminal_path_count_capped"] < 1:
                raise ValueError(f"H016-v2 positive has no terminal path: {job_id}")
            path_checks.append(dict(job=job_id, endpoint_phase=endpoint))

        if job_id == IMPOSSIBLE_JOB_ID:
            row = output_job["pages"][0]
            if row["model_status"] != "dead" or row["final_state_count"] != 0:
                raise ValueError("H016-v2 incompatible control remained reachable")
            if row["first_dead_position"] != 1:
                raise ValueError("H016-v2 incompatible-control death position changed")
            impossible_checks.append(dict(job=job_id, status="negative"))

    actual_positive_ids = {row["job"] for row in path_checks}
    if actual_positive_ids != EXPECTED_POSITIVE_JOB_IDS or len(path_checks) != 4:
        raise ValueError(
            "H016-v2 positive validation is incomplete: "
            f"expected={sorted(EXPECTED_POSITIVE_JOB_IDS)}, actual={sorted(actual_positive_ids)}"
        )
    if len(impossible_checks) != 1:
        raise ValueError("H016-v2 incompatible-control validation is incomplete")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        public_sha256=stable_digest(public),
        positive_path_checks=path_checks,
        incompatible_checks=impossible_checks,
        independent_algorithm="forward-enumerated 13x29 transition table plus capped path recurrence",
    )


def continuous_ratio(rows, page_lengths):
    total = sum(page_lengths)
    completed = 0
    for row, length in zip(rows, page_lengths):
        if row["model_status"] == "not_reached":
            break
        if row["legal_prefix_length"] is None:
            raise ValueError("Reached row has no legal prefix length")
        completed += row["legal_prefix_length"]
        if row["model_status"] == "dead" or row["legal_prefix_length"] != length:
            break
    return completed / total if total else 1.0


def metric_vector_from_observed(output, page_order, page_lengths):
    output_map = {job["id"]: job for job in output["jobs"]}
    reset_job = output_map["unsolved-page_reset"]
    continuous_job = output_map["unsolved-continuous"]
    if [row["page"] for row in reset_job["pages"]] != page_order:
        raise ValueError("Observed page-reset metric order changed")
    values = [row["legal_prefix_ratio"] for row in reset_job["pages"]]
    values.append(continuous_ratio(continuous_job["pages"], page_lengths))
    return values


def model_units_from_observed(output, page_order):
    output_map = {job["id"]: job for job in output["jobs"]}
    reset_rows = output_map["unsolved-page_reset"]["pages"]
    continuous_job = output_map["unsolved-continuous"]
    if [row["page"] for row in reset_rows] != page_order:
        raise ValueError("Observed model-status order changed")
    statuses = [row["model_status"] for row in reset_rows]
    statuses.append("compatible" if continuous_job["final_phases"] else "dead")
    return statuses


def metric_vector_from_pages(pages):
    reset_job = independent_job(dict(id="control-page-reset", branch="page_reset", pages=pages))
    continuous_job = independent_job(dict(id="control-continuous", branch="continuous", pages=pages))
    reset_values = [row["legal_prefix_ratio"] for row in reset_job["pages"]]
    reset_values.append(
        continuous_ratio(
            continuous_job["pages"], [len(page["cipher"]) for page in pages]
        )
    )
    return reset_values


def standardize(observed, controls):
    if len(observed) != 56 or len(controls) != CONTROL_REPLICATES:
        raise ValueError("Unexpected H016-v2 metric shape")
    if any(len(row) != len(observed) for row in controls):
        raise ValueError("H016-v2 control metric width mismatch")
    values_by_unit = [[observed[index]] + [row[index] for row in controls] for index in range(56)]
    means = []
    stds = []
    for values in values_by_unit:
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


def save_checkpoint(path, *, completed, partial_path, frozen, rng, status):
    checkpoint = dict(
        schema=1,
        status=status,
        completed=completed,
        last_replicate=completed,
        requested=CONTROL_REPLICATES,
        unit_count=56,
        seed=CONTROL_SEED,
        partial_path=partial_path.name,
        partial_sha256=sha256(partial_path) if partial_path.exists() else None,
        frozen_sha256=sha256(frozen),
        code_version_digest=json.loads(frozen.read_text(encoding="utf8"))["code_version"]["digest"],
        public_sha256=json.loads(frozen.read_text(encoding="utf8"))["public_sha256"],
        rng_state_sha256=stable_digest(rng.getstate()),
        replay_rule="restart from seed and consume exactly one page-preserving shuffle per applicable page per replicate",
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
    paths.extend(
        path for path in run.rglob("*") if path.is_file() and path != archive
    )
    knowledge = json.loads((ROOT / "research/knowledge.json").read_text(encoding="utf8"))
    paths.extend(ROOT / entry["artifact"] for entry in knowledge["experiments"])
    paths.extend(ROOT / name for name in ("README.md", "AGENTS.md", "STATE.md"))
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(
        path=archive.relative_to(ROOT).as_posix(),
        sha256=sha256(archive),
        bytes=archive.stat().st_size,
    )


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
        attempt="auto-cycle R008",
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
            raise ValueError("H016-v2 specification is not preregistered")
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
        unit_order = [f"page_reset::{page}" for page in page_order] + [
            "continuous::LP2/0..55"
        ]
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
        frozen_value = dict(
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
            unit_order=unit_order,
            control_replicates=CONTROL_REPLICATES,
            control_seed=CONTROL_SEED,
            synthetic_seed_verifier_only=SYNTHETIC_SEED,
            alpha=ALPHA,
            tie_tolerance=TIE_TOLERANCE,
            path_cap=PATH_CAP,
            total_wall_seconds=WALL_SECONDS,
            checkpoint_every=CHECKPOINT_EVERY,
            expected_positive_job_ids=sorted(EXPECTED_POSITIVE_JOB_IDS),
            expected_sha256=sha256(run / "verifier-only" / "answers.json"),
            public_sha256=stable_digest(public),
        )
        write_json(frozen, frozen_value)
        record.update(
            execution_started=True,
            source_files_verified=source_count,
            frozen_sha256=sha256(frozen),
        )
        write_json(run / "record.json", record)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("H016-v2 deadline expired before worker")
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
            raise TimeoutError("H016-v2 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H016-v2 worker failed; see worker-execution.json")
        output = json.loads(execution["stdout"])
        write_json(run / "worker-output.json", output)
        verification = verify_worker(public, output, answers)
        write_json(run / "independent-verification.json", verification)
        observed = metric_vector_from_observed(output, page_order, page_lengths)
        model_statuses = model_units_from_observed(output, page_order)
        write_json(
            run / "observed.json",
            dict(
                unit_order=unit_order,
                metrics=observed,
                model_statuses=model_statuses,
                metrics_sha256=stable_digest(observed),
            ),
        )

        controls = []
        partial_path = run / "control-metrics.partial.jsonl"
        rng = random.Random(CONTROL_SEED)
        for replicate in range(1, CONTROL_REPLICATES + 1):
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"H016-v2 wall budget exceeded after {len(controls)} controls"
                )
            shuffled_pages = [
                dict(
                    page=page["page"],
                    cipher=randomize_preserving_zero_positions(page["cipher"], rng),
                )
                for page in public_pages
            ]
            metrics = metric_vector_from_pages(shuffled_pages)
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
            raise TimeoutError("H016-v2 wall budget exceeded after final control")
        write_json(
            run / "control-metrics.json",
            dict(
                schema=1,
                algorithm="fixed-zero-mask within-page nonzero permutation",
                seed=CONTROL_SEED,
                requested=CONTROL_REPLICATES,
                completed=len(controls),
                unit_order=unit_order,
                metric_rows=controls,
            ),
        )
        stats = standardize(observed, controls)
        stat_rows = []
        for unit, metric, model_status, z, p, std in zip(
            unit_order,
            observed,
            model_statuses,
            stats["observed_z"],
            stats["p_adjusted"],
            stats["stds"],
        ):
            statistic_status = "zero_variance" if std == 0 else (
                "lead" if p <= ALPHA else "not_detected"
            )
            candidate = model_status == "compatible" and statistic_status == "lead"
            stat_rows.append(
                dict(
                    unit=unit,
                    metric=metric,
                    model_status=model_status,
                    statistic_status=statistic_status,
                    candidate=candidate,
                    z=z,
                    p_adjusted=p,
                )
            )
        leads = [row for row in stat_rows if row["statistic_status"] == "lead"]
        candidates = [row for row in stat_rows if row["candidate"]]
        compatible_units = [
            row["unit"] for row in stat_rows if row["model_status"] == "compatible"
        ]
        strongest = sorted(
            stat_rows, key=lambda row: (row["p_adjusted"], -row["z"], row["unit"])
        )[:10]
        continuous_rows = next(
            job["pages"] for job in output["jobs"] if job["id"] == "unsolved-continuous"
        )
        not_reached_pages = [
            row["page"] for row in continuous_rows if row["model_status"] == "not_reached"
        ]
        reached_continuous_pages = len(continuous_rows) - len(not_reached_pages)
        summary_status = "inconclusive" if (compatible_units or leads) else "negative"
        summary = dict(
            status=summary_status,
            hypothesis=HYPOTHESIS,
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
                page_reset_reached_pages=55,
                continuous_reached_pages=reached_continuous_pages,
                continuous_not_reached_pages=not_reached_pages,
                unsolved_page_candidates=[row["unit"] for row in candidates],
            ),
            model_classification=dict(
                compatible_units=compatible_units,
                dead_units=[
                    row["unit"] for row in stat_rows if row["model_status"] == "dead"
                ],
                continuous_not_reached_pages=not_reached_pages,
            ),
            statistic_classification=dict(
                leads=leads,
                candidates=candidates,
                no_lead_units=[
                    row["unit"] for row in stat_rows
                    if row["statistic_status"] == "not_detected"
                ],
            ),
            statistic_rows=stat_rows,
            strongest=strongest,
            statistics=stats,
            state_result=(
                "Reachable states are compatibility evidence only; no plaintext path was selected or emitted."
            ),
            negative_scope=(
                "Only H016-v2's fixed FIRFUMFERENFE key, subtractive direction, modulo-13 phase, "
                "copied plaintext-F exception, two continuity branches and fixed-zero-mask permutation null."
            ),
            classification_policy=(
                "compatible/dead/not_reached are model statuses; lead/not_detected/zero_variance are "
                "statistic statuses. A dead prefix with a statistical lead is not a candidate."
            ),
            limitation=(
                "No independent LP2 plaintext or image-level glyph audit is available; LP2/50 literal grid is unexecuted."
            ),
        )
        write_json(run / "statistics.json", summary)
        record.update(
            status=summary["status"],
            result=dict(
                leads=len(leads),
                compatible_units=len(compatible_units),
                candidates=len(candidates),
                strongest=strongest[:3],
            ),
            actual_coverage=summary["coverage"],
            unsolved_page_candidates=summary["coverage"]["unsolved_page_candidates"],
        )
        if code_snapshot(ROOT) != snapshot or any(
            sha256(ROOT / path) != value for path, value in source_hashes.items()
        ):
            raise ValueError("Frozen H016-v2 code or source input changed during execution")
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
