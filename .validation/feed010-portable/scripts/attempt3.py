"""Execute the preregistered H007 finite-state reachability batch."""

from __future__ import annotations

from pathlib import Path
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
from lp_lab.reference import reference_indices
from lp_lab.runes import RUNES, indices
from lp_lab.synthetic import encode_text


SPEC = "hypotheses/H007-finite-state-v1.json"
CORPUS = "data/attempt1-corpus-v1.json"
KNOWN = "data/pages/lp2_56.json"
KNOWN_REFERENCE = "sources/ibot/liber_primus/markdown/73.md"
HELDOUT = "data/synthetic/heldout.txt"
CONTINUITIES = ("continuous", "page_reset")
CONTROL_SEEDS = (33010711, 33010712, 33010713)
SYNTHETIC_SEED = 33010703


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )


def object_digest(value) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def independent_deltas(count: int) -> tuple[int, ...]:
    """Generate the same mathematical stream with a separate implementation."""
    if type(count) is not int or count < 0:
        raise ValueError("Invalid independent prime count")
    primes = []
    candidate = 2
    while len(primes) < count:
        if all(
            candidate % prime for prime in primes if prime * prime <= candidate
        ):
            primes.append(candidate)
        candidate += 1
    return tuple((prime - 1) % 29 for prime in primes)


def _digest_state_history(history, width: int) -> str:
    digest = hashlib.sha256()
    for states in history:
        mask = sum(1 << clock for clock in states)
        digest.update(mask.to_bytes(width, "little"))
    return digest.hexdigest()


def independent_scan(cipher, starts, deltas):
    """Set-based verifier; deliberately separate from the worker bitset code."""
    if any(clock < 0 or clock >= len(deltas) for clock in starts):
        raise ValueError("Independent start clock outside stream")
    states = set(starts)
    ways = {clock: 1 for clock in starts}
    history = [set(states)]
    state_counts = [len(states)]
    ordinary_edges = 0
    exception_edges = 0
    first_dead_position = None

    for position, cipher_value in enumerate(cipher):
        next_states = set()
        next_ways = {}
        if cipher_value == 0:
            exception_edges += len(states)
        for clock, count in ways.items():
            delta = deltas[clock]
            if cipher_value == 0:
                next_states.add(clock)
                next_ways[clock] = min(2, next_ways.get(clock, 0) + count)
                if delta != 0:
                    ordinary_edges += 1
                    next_states.add(clock + 1)
                    next_ways[clock + 1] = min(
                        2, next_ways.get(clock + 1, 0) + count
                    )
            elif cipher_value != delta:
                ordinary_edges += 1
                next_states.add(clock + 1)
                next_ways[clock + 1] = min(
                    2, next_ways.get(clock + 1, 0) + count
                )
        states = next_states
        ways = next_ways
        history.append(set(states))
        state_counts.append(len(states))
        if not states and first_dead_position is None:
            first_dead_position = position

    max_clock = max(len(deltas), max(starts, default=0))
    width = max_clock // 8 + 1
    terminal_paths = min(2, sum(ways.values()))
    return dict(
        initial_clocks=sorted(starts),
        rune_count=len(cipher),
        zero_cipher_runes=sum(value == 0 for value in cipher),
        state_counts=state_counts,
        max_state_count=max(state_counts, default=0),
        final_clocks=sorted(ways),
        final_state_count=len(ways),
        terminal_path_count_capped=terminal_paths,
        unique_terminal_path=(len(ways) == 1 and terminal_paths == 1),
        ordinary_edges=ordinary_edges,
        exception_edges=exception_edges,
        total_edges=ordinary_edges + exception_edges,
        first_dead_position=first_dead_position,
        state_digest=_digest_state_history(history, width),
    )


def load_corpus():
    corpus = json.loads((ROOT / CORPUS).read_text(encoding="utf8"))
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
    if len(public_pages) != 55 or [p["page"] for p in metadata if not p["rune_count"]] != ["LP2/50"]:
        raise ValueError("H007 applicability scope changed")
    return pages, public_pages, metadata


def load_known_control():
    record = json.loads((ROOT / KNOWN).read_text(encoding="utf8"))
    raw = record["raw"]
    cipher = indices(raw)
    expected = reference_indices(ROOT / KNOWN_REFERENCE)
    if len(cipher) != 85 or len(expected) != 85:
        raise ValueError("Known LP2/56 length changed")
    if record["cross_source"]["path"] != KNOWN_REFERENCE:
        raise ValueError("Known reference path changed")
    if [i for i, value in enumerate(expected) if value == 0] != [56]:
        raise ValueError("Known LP2/56 F exception position changed")
    return (
        dict(page="LP2/56", cipher=cipher),
        dict(
            kind="known",
            page="LP2/56",
            plaintext=expected,
            exception_ordinals=[56],
            expected_final_clock=84,
            source=KNOWN_REFERENCE,
            source_sha256=sha256(ROOT / KNOWN_REFERENCE),
        ),
    )


def h007_encrypt(plain):
    deltas = independent_deltas(len(plain))
    cipher = []
    clock = 0
    for value in plain:
        if type(value) is not int or not 0 <= value < 29:
            raise ValueError("Synthetic plaintext outside rune domain")
        if value == 0:
            cipher.append(0)
        else:
            cipher.append((value + deltas[clock]) % 29)
            clock += 1
    return cipher, clock


def synthetic_controls():
    heldout = encode_text((ROOT / HELDOUT).read_text(encoding="utf8"))
    if len(heldout) < 384:
        raise ValueError("Heldout control text is too short")
    plans = [
        ("synthetic-heldout-head", heldout[:128]),
        ("synthetic-heldout-middle", heldout[128:256]),
    ]
    rng = random.Random(SYNTHETIC_SEED)
    random_plain = [rng.randrange(29) for _ in range(128)]
    random_plain[17] = 0
    plans.append(("synthetic-random-plain", random_plain))
    jobs = []
    answers = {}
    for job_id, plain in plans:
        cipher, final_clock = h007_encrypt(plain)
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
        answers[job_id] = dict(
            kind="synthetic_positive",
            page=job_id,
            plaintext=plain,
            expected_final_clock=final_clock,
            source=HELDOUT if job_id != "synthetic-random-plain" else None,
            seed=SYNTHETIC_SEED if job_id == "synthetic-random-plain" else None,
        )
    return jobs, answers


def random_controls():
    jobs = []
    for seed in CONTROL_SEEDS:
        rng = random.Random(seed)
        job_id = f"random-control-{seed}"
        cipher = [rng.randrange(29) for _ in range(96)]
        jobs.append(dict(id=job_id, pages=[dict(page=job_id, cipher=cipher)]))
    return jobs


def make_public_and_answers(corpus_pages):
    known_page, known_answer = load_known_control()
    synthetic_jobs, answers = synthetic_controls()
    jobs = [dict(id="unsolved-corpus", pages=corpus_pages)]
    jobs.append(dict(id="known-lp2-56", pages=[known_page]))
    jobs.extend(synthetic_jobs)
    jobs.append(dict(id="incompatible-control", pages=[dict(page="incompatible-control", cipher=[1])]))
    jobs.extend(random_controls())
    answers["known-lp2-56"] = known_answer
    return dict(schema=1, hypothesis="H007-v1", continuities=list(CONTINUITIES), jobs=jobs), answers


def replay_expected(cipher, plain, deltas):
    """Return the expected endpoint clock if a private path is legal."""
    if len(cipher) != len(plain):
        raise ValueError("Expected path length mismatch")
    clock = 0
    for position, (cipher_value, plain_value) in enumerate(zip(cipher, plain)):
        if plain_value == 0:
            if cipher_value != 0:
                raise ValueError(f"Expected F path has nonzero C at {position}")
        else:
            if cipher_value != (plain_value + deltas[clock]) % 29:
                raise ValueError(f"Expected path arithmetic mismatch at {position}")
            clock += 1
    return clock


SUMMARY_FIELDS = (
    "initial_clocks",
    "rune_count",
    "zero_cipher_runes",
    "state_counts",
    "max_state_count",
    "final_clocks",
    "final_state_count",
    "terminal_path_count_capped",
    "unique_terminal_path",
    "ordinary_edges",
    "exception_edges",
    "total_edges",
    "first_dead_position",
    "state_digest",
)


def verify_worker(public, output, answers):
    if not output.get("read_guard_probe_passed"):
        raise ValueError("Worker read isolation probe failed")
    if [job["id"] for job in output.get("jobs", [])] != [job["id"] for job in public["jobs"]]:
        raise ValueError("Worker omitted or reordered jobs")
    expected_checks = []
    dead_checks = []
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        if output_job["total_runes"] != sum(len(page["cipher"]) for page in public_job["pages"]):
            raise ValueError("Worker total rune count mismatch")
        deltas = independent_deltas(output_job["total_runes"])
        prior_states = (0,)
        for continuity in CONTINUITIES:
            if output_job["branches"][continuity]["continuity"] != continuity:
                raise ValueError("Worker branch label mismatch")
            expected_pages = []
            states = (0,)
            for page in public_job["pages"]:
                starts = states if continuity == "continuous" else (0,)
                expected = independent_scan(page["cipher"], starts, deltas)
                expected["page"] = page["page"]
                expected_pages.append(expected)
                if continuity == "continuous":
                    states = tuple(expected["final_clocks"])
            actual_branch = output_job["branches"][continuity]
            if [row["page"] for row in actual_branch["pages"]] != [row["page"] for row in expected_pages]:
                raise ValueError("Worker page coverage mismatch")
            for actual, expected in zip(actual_branch["pages"], expected_pages):
                if any(actual.get(field) != expected[field] for field in SUMMARY_FIELDS):
                    raise ValueError(f"Independent H007 state check failed: {public_job['id']}/{continuity}/{actual['page']}")
            expected_final = sorted(states) if continuity == "continuous" else None
            if actual_branch.get("final_clocks") != expected_final:
                raise ValueError("Worker batch final state mismatch")
            if public_job["id"] in answers:
                answer = answers[public_job["id"]]
                page = public_job["pages"][0]
                endpoint = replay_expected(page["cipher"], answer["plaintext"], deltas)
                row = actual_branch["pages"][0]
                if endpoint not in row["final_clocks"]:
                    raise ValueError(f"Private expected path is not reachable: {public_job['id']}/{continuity}")
                if endpoint != answer["expected_final_clock"]:
                    raise ValueError("Private expected endpoint changed")
                expected_checks.append(dict(job=public_job["id"], continuity=continuity, endpoint_clock=endpoint))
            if public_job["id"] == "incompatible-control":
                if any(row["final_state_count"] for row in actual_branch["pages"]):
                    raise ValueError("Incompatible control unexpectedly remained reachable")
                dead_checks.append(dict(job=public_job["id"], continuity=continuity, status="negative"))
            prior_states = states
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        worker_branches=len(CONTINUITIES),
        expected_path_checks=expected_checks,
        incompatible_control_checks=dead_checks,
        independent_algorithm="set recurrence with capped path multiplicity and independent prime generation",
        public_sha256=object_digest(public),
    )


def corpus_rows(public, output, run, execution):
    job = next(job for job in public["jobs"] if job["id"] == "unsolved-corpus")
    actual = next(job for job in output["jobs"] if job["id"] == "unsolved-corpus")
    rows = []
    for continuity in CONTINUITIES:
        branch = actual["branches"][continuity]
        upstream_dead_page = None
        for page in branch["pages"]:
            detail_path = run / "page-summaries" / f"{page['page'].replace('/', '_')}-{continuity}.json"
            write(detail_path, dict(page=page["page"], continuity=continuity, state_summary=page))
            reachable = page["final_state_count"] > 0
            downstream_of_dead_prefix = continuity == "continuous" and not page["initial_clocks"]
            if downstream_of_dead_prefix:
                row_status = "inconclusive"
                incomplete_reason = (
                    f"Continuous state set was already empty after {upstream_dead_page}; "
                    "this page was not independently negative."
                )
            else:
                row_status = "inconclusive" if reachable else "negative"
                incomplete_reason = (
                    "Reachability is compatible-state evidence only; no plaintext path was selected or accepted."
                    if reachable
                    else None
                )
            rows.append(
                dict(
                    page_or_section=page["page"],
                    applicability=True,
                    inapplicability_reason=None,
                    method_id="H007-v1",
                    actual_parameter_coverage=dict(
                        continuity=continuity,
                        prime_stream="prime[t]-1 mod29; offset=0; shift=1; subtractive",
                        rune_count=page["rune_count"],
                        zero_cipher_runes=page["zero_cipher_runes"],
                        initial_clocks=page["initial_clocks"],
                        initial_state_count=len(page["initial_clocks"]),
                        max_state_count=page["max_state_count"],
                        final_state_count=page["final_state_count"],
                        terminal_path_count_capped=page["terminal_path_count_capped"],
                        unique_terminal_path=page["unique_terminal_path"],
                        ordinary_edges=page["ordinary_edges"],
                        exception_edges=page["exception_edges"],
                        first_dead_position=page["first_dead_position"],
                        state_digest=page["state_digest"],
                    ),
                    uncovered_parameters=[
                        "language scoring",
                        "unknown key/offset/shift families",
                        "literal/grid consumption",
                        "line/paragraph/hash/delimiter resets",
                    ],
                    result_status=row_status,
                    candidate_evidence=[],
                    state_summary_path=detail_path.relative_to(ROOT).as_posix(),
                    elapsed_seconds=execution["elapsed_seconds"],
                    elapsed_scope="shared H007 worker batch",
                    exit_code=execution["exit_code"],
                    stdout_path=(run / "stdout.json").relative_to(ROOT).as_posix(),
                    stderr_path=(run / "stderr.txt").relative_to(ROOT).as_posix(),
                    incomplete_reason=incomplete_reason,
                )
            )
            if continuity == "continuous" and not reachable and page["initial_clocks"] and upstream_dead_page is None:
                upstream_dead_page = page["page"]
    for page in json.loads((ROOT / CORPUS).read_text(encoding="utf8"))["pages"]:
        if page["rune_count"] == 0:
            rows.append(
                dict(
                    page_or_section=page["page"],
                    applicability=False,
                    inapplicability_reason="No registered rune tokens; literal grid is outside H007 and is not a negative result.",
                    method_id="H007-v1",
                    actual_parameter_coverage=[],
                    uncovered_parameters=[],
                    result_status="inconclusive",
                    candidate_evidence=[],
                    elapsed_seconds=0.0,
                    exit_code=None,
                    stdout_path=None,
                    stderr_path=None,
                    incomplete_reason="not applicable to the rune-domain state model",
                )
            )
    return rows


def summarize_corpus(rows):
    summary = {}
    for continuity in CONTINUITIES:
        scoped = [
            row for row in rows
            if row["applicability"] and row["actual_parameter_coverage"]["continuity"] == continuity
        ]
        summary[continuity] = dict(
            applicable_pages=len(scoped),
            reachable_pages=sum(row["actual_parameter_coverage"]["final_state_count"] > 0 for row in scoped),
            dead_pages=sum(
                row["result_status"] == "negative" and row["actual_parameter_coverage"]["initial_state_count"] > 0
                for row in scoped
            ),
            downstream_unreached_pages=sum(
                row["actual_parameter_coverage"]["initial_state_count"] == 0 for row in scoped
            ),
            inconclusive_rows=sum(row["result_status"] == "inconclusive" for row in scoped),
            first_prefix_dead_page=next(
                (
                    row["page_or_section"]
                    for row in scoped
                    if row["actual_parameter_coverage"]["initial_state_count"] > 0
                    and row["actual_parameter_coverage"]["final_state_count"] == 0
                ),
                None,
            ),
            unique_terminal_path_pages=sum(
                row["actual_parameter_coverage"]["unique_terminal_path"] for row in scoped
            ),
            max_state_count=max(
                (row["actual_parameter_coverage"]["max_state_count"] for row in scoped),
                default=0,
            ),
        )
    return summary


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Run folder must be inside repository runs")
    run.mkdir(parents=True, exist_ok=False)
    started = dt.datetime.now(dt.timezone.utc)
    stopwatch = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(
        schema=1,
        attempt="attempt 3",
        hypothesis="H007-finite-state-v1",
        status="running",
        started_at_utc=started.isoformat(),
        python=sys.version,
        executable=sys.executable,
        platform=platform.platform(),
        code_version=snapshot,
        execution_started=False,
    )
    write(run / "record.json", record)
    try:
        record["sources_verified"] = verify_sources(ROOT)
        spec = json.loads((ROOT / SPEC).read_text(encoding="utf8"))
        pages, corpus_public_pages, metadata = load_corpus()
        public, answers = make_public_and_answers(corpus_public_pages)
        source_paths = [CORPUS, KNOWN, KNOWN_REFERENCE, HELDOUT, SPEC]
        source_paths += [p.relative_to(ROOT).as_posix() for p in (ROOT / "sources").glob("*manifest.json")]
        source_hashes = {path: sha256(ROOT / path) for path in source_paths}
        write(run / "inputs.json", dict(
            schema=1,
            derived_at_utc=started.isoformat(),
            corpus_version="attempt1-corpus-v1",
            pages=metadata,
            control_jobs=[job["id"] for job in public["jobs"] if job["id"] != "unsolved-corpus"],
            public_sha256=object_digest(public),
        ))
        write(run / "verifier-only" / "answers.json", answers)
        write(run / "public.json", public)
        freeze = dict(
            frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            specification=spec,
            source_hashes=source_hashes,
            code_version=snapshot,
            inputs_sha256=sha256(run / "inputs.json"),
            public_sha256=sha256(run / "public.json"),
            expected_sha256=sha256(run / "verifier-only" / "answers.json"),
            jobs=len(public["jobs"]),
            continuity_branches=list(CONTINUITIES),
            maximum_worker_seconds=120,
            no_language_scorer=True,
        )
        write(run / "frozen.json", freeze)
        record.update(
            execution_started=True,
            dispatched_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            frozen_sha256=sha256(run / "frozen.json"),
        )
        write(run / "record.json", record)
        execution = execute(
            [sys.executable, "-I", "-S", str(ROOT / "scripts/attempt3_worker.py")],
            cwd=ROOT,
            timeout=120,
            stdin=json.dumps(public),
        )
        write(run / "execution.json", execution)
        (run / "stdout.json").write_text(execution["stdout"], encoding="utf8")
        (run / "stderr.txt").write_text(execution["stderr"], encoding="utf8")
        if execution["status"] == "timeout":
            raise TimeoutError("H007 worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("H007 worker failed; see execution.json and stderr.txt")
        output = json.loads(execution["stdout"])
        verification = verify_worker(public, output, answers)
        write(run / "independent-verification.json", verification)
        rows = corpus_rows(public, output, run, execution)
        write(run / "coverage.json", dict(schema=1, rows=rows))
        corpus_summary = summarize_corpus(rows)
        reachable = sum(branch["reachable_pages"] for branch in corpus_summary.values())
        result_status = "inconclusive" if reachable else "negative"
        summary = dict(
            status=result_status,
            controls_status=verification["status"],
            hypothesis="H007-finite-state-v1",
            corpus_pages=55,
            corpus_runes=sum(page["rune_count"] for page in pages),
            continuity_summary=corpus_summary,
            reachable_page_branch_rows=reachable,
            deciphered_new_pages=[],
            language_score_used=False,
            interpretation="Surviving states are compatibility evidence, not selected plaintext or a decrypted page.",
            rows=rows,
        )
        write(run / "summary.json", summary)
        record.update(
            status=result_status,
            controls_status=verification["status"],
            corpus_runes=summary["corpus_runes"],
            reachable_page_branch_rows=reachable,
            deciphered_new_pages=[],
            actual_coverage=dict(
                applicable_pages=55,
                excluded_pages=["LP2/50"],
                rune_count=summary["corpus_runes"],
                continuity_branches=list(CONTINUITIES),
                control_jobs=len(public["jobs"]) - 1,
            ),
        )
        if code_snapshot(ROOT) != snapshot or any(sha256(ROOT / path) != value for path, value in source_hashes.items()):
            raise ValueError("Frozen code or input changed during H007")
        verify_sources(ROOT)
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc))
        (run / "exception.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    record.update(finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - stopwatch)
    write(run / "record.json", record)

    files = [ROOT / path for path in snapshot["files"]]
    for directory in ("sources", "data", "hypotheses", "research"):
        files.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    knowledge = json.loads((ROOT / "research/knowledge.json").read_text(encoding="utf8"))
    files.extend(ROOT / entry["artifact"] for entry in knowledge["experiments"])
    files.extend(ROOT / name for name in ("README.md", "AGENTS.md", "STATE.md"))
    files.extend(path for path in run.rglob("*") if path.is_file())
    archive = run / "attempt3-bundle.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(files)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    write(run / "bundle-integrity.json", dict(path=archive.name, sha256=sha256(archive), members=len(set(files))))
    print(json.dumps(dict(
        run=run.relative_to(ROOT).as_posix(),
        status=record["status"],
        controls_status=record.get("controls_status"),
        corpus_runes=record.get("corpus_runes"),
        reachable_page_branch_rows=record.get("reachable_page_branch_rows"),
        deciphered_new_pages=record.get("deciphered_new_pages"),
        elapsed_seconds=record.get("elapsed_seconds"),
        error=record.get("error"),
    ), ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
