"""Continue the paused H030-v2 control stream under an explicit v3 contract.

The four-view BM model and all scientific thresholds are inherited unchanged.
The old 0..199 control rows are independently regenerated and checked before
rows 200..998 are appended, so the result cannot silently mix a new random
stream with the user-paused one.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import json
import math
import sys
import time
import traceback

import attempt21_bm_v2 as base


ROOT = Path(__file__).resolve().parents[1]
HYPOTHESIS = "H030-berlekamp-massey-v3"
SPEC_PATH = ROOT / "hypotheses/H030-berlekamp-massey-v3.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
WORKER_PATH = ROOT / "scripts/attempt21_bm_v3_worker.py"
SOURCE_RUN = ROOT / "runs/auto-cycle-r015-H030-v2-retry3"
SOURCE_PARTIAL = SOURCE_RUN / "control-results.partial.json"
SOURCE_RECORD = SOURCE_RUN / "record.json"
SOURCE_FROZEN = SOURCE_RUN / "frozen.json"
CONTROL_COUNT = 999
CONTROL_SEED = 33011521
ALPHA = 0.01 / 3.0
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 3600
RESUME_COUNT = 200
EXPECTED_PAGE_ORDER = [f"LP2/{i}" for i in range(56)]
EXPECTED_APPLICABLE_ORDER = [page for page in EXPECTED_PAGE_ORDER if page != "LP2/50"]
EXPECTED_VIEW_NAMES = list(base.VIEW_NAMES)


def write_json(path: Path, value) -> None:
    base.write_json(path, value)


def write_json_atomic(path: Path, value) -> None:
    """Write a checkpoint/partial without leaving a half-written JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(base.json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
    )
    temporary.replace(path)


def sha256(path: Path) -> str:
    return base.sha256(path)


def canonical(value) -> str:
    """Canonical JSON used for strict source-row comparisons."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assert_worker_result_contract(output: dict, jobs: list[dict], name: str) -> None:
    """Reject duplicate/missing/reordered result rows before dict normalization."""
    if output.get("status") != "completed":
        raise ValueError(f"H030-v3 worker status drifted: {name}")
    if not isinstance(output.get("results"), list):
        raise ValueError(f"H030-v3 worker results are not a list: {name}")
    expected_ids = [job["id"] for job in jobs]
    actual_ids = []
    for row in output["results"]:
        if not isinstance(row, dict) or set(row) != {"id", "sequence_length", "views"}:
            raise ValueError(f"H030-v3 worker row fields drifted: {name}")
        actual_ids.append(row["id"])
        if not isinstance(row["id"], str):
            raise ValueError(f"H030-v3 worker row id type drifted: {name}")
        if not isinstance(row["views"], dict) or set(row["views"]) != set(EXPECTED_VIEW_NAMES):
            raise ValueError(f"H030-v3 worker view coverage drifted: {name}:{row.get('id')}")
        if any(not isinstance(row["views"][view], dict) for view in EXPECTED_VIEW_NAMES):
            raise ValueError(f"H030-v3 worker metric row is not an object: {name}:{row.get('id')}")
    if len(actual_ids) != len(expected_ids) or actual_ids != expected_ids:
        raise ValueError(f"H030-v3 worker result ids/order drifted: {name}")
    if len(set(actual_ids)) != len(actual_ids):
        raise ValueError(f"H030-v3 worker result ids are not unique: {name}")
    for row, job in zip(output["results"], jobs):
        if type(row["sequence_length"]) is not int or row["sequence_length"] != len(job["cipher"]):
            raise ValueError(f"H030-v3 worker sequence length mismatch: {name}:{job['id']}")


def remaining_worker_timeout(started: float, requested: int = 900) -> int:
    remaining = WALL_SECONDS - (time.monotonic() - started)
    if remaining <= 0:
        raise TimeoutError("H030-v3 wall budget exhausted before worker dispatch")
    return max(1, min(requested, math.ceil(remaining)))


def run_worker(run: Path, name: str, jobs: list[dict], *, started: float, timeout: int = 900) -> dict:
    folder = run / "worker" / name
    folder.mkdir(parents=True, exist_ok=True)
    public = dict(schema=1, hypothesis=HYPOTHESIS, jobs=jobs)
    write_json(folder / "public.json", public)
    result = base.execute(
        [sys.executable, "-I", "-S", "-X", "utf8", str(WORKER_PATH)],
        cwd=ROOT,
        timeout=remaining_worker_timeout(started, timeout),
        stdin=json.dumps(public, ensure_ascii=False),
    )
    write_json(folder / "execution.json", result)
    (folder / "stdout.json").write_text(result["stdout"], encoding="utf8")
    (folder / "stderr.txt").write_text(result["stderr"], encoding="utf8")
    if result["status"] != "completed":
        if result["status"] == "timeout":
            raise TimeoutError(f"H030-v3 worker {name} timed out")
        raise RuntimeError(f"H030-v3 worker {name} failed")
    output = json.loads(result["stdout"])
    if not output.get("read_guard_probe_passed"):
        raise RuntimeError(f"H030-v3 worker read guard failed: {name}")
    if output.get("view_names") != EXPECTED_VIEW_NAMES:
        raise ValueError(f"H030-v3 worker view contract drifted: {name}")
    assert_worker_result_contract(output, jobs, name)
    return output


def validate_resume_rows(applicable: list[dict]) -> tuple[list[dict], dict]:
    if not SOURCE_PARTIAL.is_file():
        raise FileNotFoundError(SOURCE_PARTIAL)
    source_record = json.loads(SOURCE_RECORD.read_text(encoding="utf8"))
    source_frozen = json.loads(SOURCE_FROZEN.read_text(encoding="utf8"))
    if source_record.get("hypothesis") != "H030-berlekamp-massey-v2":
        raise ValueError("H030-v3 source record hypothesis mismatch")
    if source_record.get("status") != "error" or source_record.get("gate_status") != "passed":
        raise ValueError("H030-v3 source record is not the verified paused v2 run")
    if source_record.get("gate_positive_passes") != 20 or source_record.get("gate_negative_false_accepts") != 0:
        raise ValueError("H030-v3 source gate record mismatch")
    if "200/999" not in str(source_record.get("error", "")):
        raise ValueError("H030-v3 source record lacks the 200/999 checkpoint declaration")
    if source_record.get("code_version", {}).get("digest") != source_frozen.get("code_version", {}).get("digest"):
        raise ValueError("H030-v3 source code snapshot linkage mismatch")
    if source_frozen.get("page_order") != EXPECTED_PAGE_ORDER:
        raise ValueError("H030-v3 source frozen page order mismatch")
    if source_frozen.get("discovery") != list(base.DISCOVERY) or source_frozen.get("holdout") != list(base.HOLDOUT):
        raise ValueError("H030-v3 source frozen partition mismatch")
    if source_frozen.get("excluded") != ["LP2/50"] or source_frozen.get("views") != EXPECTED_VIEW_NAMES:
        raise ValueError("H030-v3 source frozen object contract mismatch")
    if source_frozen.get("field") != "F29" or source_frozen.get("minimum_length") != base.MIN_LENGTH:
        raise ValueError("H030-v3 source frozen BM contract mismatch")
    if source_frozen.get("prefix_rule") != "floor(2N/3)" or source_frozen.get("max_order_rule") != "min(16,floor(prefix_length/4))":
        raise ValueError("H030-v3 source frozen prefix/order contract mismatch")
    source_controls = source_frozen.get("controls", {})
    if source_controls.get("count") != CONTROL_COUNT or source_controls.get("seed") != CONTROL_SEED:
        raise ValueError("H030-v3 source frozen control contract mismatch")
    if not str(source_controls.get("null", "")).startswith("within-page permutation before"):
        raise ValueError("H030-v3 source frozen null contract mismatch")
    if source_frozen.get("alpha") != ALPHA or source_frozen.get("tie_tolerance") != TIE_TOLERANCE:
        raise ValueError("H030-v3 source frozen statistic contract mismatch")
    if source_frozen.get("rune_count") != 12956:
        raise ValueError("H030-v3 source frozen rune count mismatch")
    rows = json.loads(SOURCE_PARTIAL.read_text(encoding="utf8"))
    if not isinstance(rows, list) or len(rows) != RESUME_COUNT:
        raise ValueError(f"Expected exactly {RESUME_COUNT} prior H030 rows")
    if [page["page"] for page in applicable] != EXPECTED_APPLICABLE_ORDER:
        raise ValueError("H030-v3 applicable page order changed")
    checked = []
    for replicate, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"replicate", "input_sha256", "pages"}:
            raise ValueError(f"H030-v3 prior row fields drifted: {replicate}")
        if type(row.get("replicate")) is not int or row.get("replicate") != replicate:
            raise ValueError(f"H030-v3 prior replicate index mismatch: {replicate}")
        if type(row.get("input_sha256")) is not str or len(row["input_sha256"]) != 64:
            raise ValueError(f"H030-v3 prior input digest type mismatch: {replicate}")
        controlled, expected_digest = base.make_control_values(applicable, replicate)
        if row.get("input_sha256") != expected_digest:
            raise ValueError(f"H030-v3 prior input digest mismatch: {replicate}")
        expected_pages = {
            page["page"]: base.compact_metrics(base.all_metrics(page["values"]))
            for page in controlled
        }
        if canonical(row.get("pages")) != canonical(expected_pages):
            raise ValueError(f"H030-v3 prior compact metrics mismatch: {replicate}")
        checked.append(row)
    return checked, dict(
        status="passed",
        source_run=SOURCE_RUN.relative_to(ROOT).as_posix(),
        requested=RESUME_COUNT,
        first_replicate=0,
        last_replicate=RESUME_COUNT - 1,
        source_partial_sha256=sha256(SOURCE_PARTIAL),
        source_record_sha256=sha256(SOURCE_RECORD),
        source_frozen_sha256=sha256(SOURCE_FROZEN),
        source_record_controls_completed=source_record.get("controls_completed"),
        source_rows_preserved=True,
        replay_rule="recompute each page with Random(CONTROL_SEED + replicate) and compare input_sha256 plus compact metrics",
    )


def save_checkpoint(run: Path, frozen: Path, completed: int, status: str) -> None:
    partial = run / "control-results.partial.json"
    checkpoint = dict(
        schema=1,
        status=status,
        completed=completed,
        requested=CONTROL_COUNT,
        next_replicate=completed,
        seed=CONTROL_SEED,
        replicate_indexing="0-based",
        source_run=SOURCE_RUN.relative_to(ROOT).as_posix(),
        source_completed=RESUME_COUNT,
        partial_sha256=sha256(partial),
        frozen_sha256=sha256(frozen),
        replay_rule="each replicate uses Random(CONTROL_SEED + replicate); source rows 0..199 are checked, rows 200..998 are newly generated",
    )
    write_json_atomic(run / "control-checkpoint.json", checkpoint)


def validate_control_rows(controls: list[dict], applicable: list[dict]) -> None:
    """Check the complete combined matrix before any statistic is computed."""
    if len(controls) != CONTROL_COUNT:
        raise ValueError(f"H030-v3 combined control count mismatch: {len(controls)}")
    expected_pages = [page["page"] for page in applicable]
    if expected_pages != EXPECTED_APPLICABLE_ORDER:
        raise ValueError("H030-v3 combined applicable page order changed")
    for replicate, row in enumerate(controls):
        if not isinstance(row, dict) or set(row) != {"replicate", "input_sha256", "pages"}:
            raise ValueError(f"H030-v3 combined row fields drifted: {replicate}")
        if type(row["replicate"]) is not int or row["replicate"] != replicate:
            raise ValueError(f"H030-v3 combined replicate index mismatch: {replicate}")
        if type(row["input_sha256"]) is not str or len(row["input_sha256"]) != 64:
            raise ValueError(f"H030-v3 combined input digest type mismatch: {replicate}")
        if list(row["pages"]) != expected_pages:
            raise ValueError(f"H030-v3 combined page order mismatch: {replicate}")
        for page_id in expected_pages:
            metrics = row["pages"][page_id]
            if not isinstance(metrics, dict) or set(metrics) != set(EXPECTED_VIEW_NAMES):
                raise ValueError(f"H030-v3 combined view coverage mismatch: {replicate}:{page_id}")
            for view in EXPECTED_VIEW_NAMES:
                if not isinstance(metrics[view], dict):
                    raise ValueError(f"H030-v3 combined metric row mismatch: {replicate}:{page_id}:{view}")


def statistic_summary(observed_metrics: dict, controls: list[dict], applicable: list[dict]) -> dict:
    control_lookup = [
        {
            page_id: {name: row["pages"][page_id][name] for name in base.VIEW_NAMES}
            for page_id in row["pages"]
        }
        for row in controls
    ]
    stats_l = base.statistic_rows(observed_metrics, control_lookup, applicable, "t_l")
    stats_p = base.statistic_rows(observed_metrics, control_lookup, applicable, "t_p")
    l_map = {(row["page"], row["view"]): row for row in stats_l}
    p_map = {(row["page"], row["view"]): row for row in stats_p}
    leads = []
    for key, l_row in l_map.items():
        p_row = p_map[key]
        observed_row = observed_metrics[key[0]][key[1]]
        full_suffix = (
            observed_row["status"] == "eligible"
            and observed_row["order"] <= observed_row["max_order"]
            and observed_row["predicted_hits"] == observed_row["suffix_length"]
        )
        if (
            key[0] in base.HOLDOUT
            and full_suffix
            and l_row["max_t_p"] <= ALPHA
            and p_row["max_t_p"] <= ALPHA
        ):
            leads.append(dict(page=key[0], view=key[1], t_l=l_row, t_p=p_row))
    strongest = sorted(
        (
            dict(page=key[0], view=key[1], t_l=l_map[key], t_p=p_map[key])
            for key in l_map
        ),
        key=lambda row: (
            row["t_l"]["max_t_p"],
            row["t_p"]["max_t_p"],
            row["page"],
            row["view"],
        ),
    )[:20]
    return dict(
        status="inconclusive" if leads else "negative",
        accepted=False,
        execution_status="pending_final_deadline_check",
        verification_status="passed",
        controls_completed=len(controls),
        leads=leads,
        strongest=strongest,
        statistics=dict(T_L=stats_l, T_P=stats_p),
        coverage=dict(
            pages=55,
            applicable_pages=55,
            excluded_pages=["LP2/50"],
            runes=12956,
            view_count=len(base.VIEW_NAMES),
            eligible_cells=len(stats_l),
            controls=len(controls),
        ),
        negative_scope="Only the four fixed representations, F29 BM protocol, page reset, prefix fraction, order cap and within-page permutation null.",
        continuation=dict(
            source_completed=RESUME_COUNT,
            newly_generated=len(controls) - RESUME_COUNT,
            combined_replicates=len(controls),
        ),
    )


def mark_deadline(run: Path, statistics_path: Path, *, before: float, after: float | None) -> dict:
    accepted = before < WALL_SECONDS and (after is None or after < WALL_SECONDS)
    audit = dict(
        schema=1,
        status="passed" if accepted else "timeout",
        before_statistics_final_verification_seconds=before,
        after_statistics_final_verification_seconds=after,
        wall_seconds=WALL_SECONDS,
        checked_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    summary = json.loads(statistics_path.read_text(encoding="utf8"))
    summary["accepted"] = accepted
    summary["execution_status"] = "accepted" if accepted else "timeout"
    summary["deadline_check"] = audit
    write_json(statistics_path, summary)
    write_json(run / "deadline-check.json", audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("H030-v3 run must be inside runs/")
    run.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc)
    snapshot = base.code_snapshot(ROOT)
    record = dict(
        schema=1,
        hypothesis=HYPOTHESIS,
        attempt="auto-cycle R015-B v3 continuation",
        status="running",
        started_at_utc=started_at.isoformat(),
        python=sys.version,
        executable=sys.executable,
        platform=__import__("platform").platform(),
        code_version=snapshot,
        controls_completed=0,
        unsolved_page_candidates=[],
    )
    write_json(run / "record.json", record)
    summary = None
    try:
        source_count = base.verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        if spec.get("id") != HYPOTHESIS or spec.get("status") != "preregistered":
            raise ValueError("H030-v3 specification is not preregistered")
        for source in spec["sources"]:
            if "sha256" in source and sha256(ROOT / source["path"]) != source["sha256"]:
                raise ValueError(f"H030-v3 source hash changed: {source['path']}")
        pages = base.load_pages()
        applicable = [page for page in pages if page["values"]]
        frozen = dict(
            schema=1,
            frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            specification_sha256=sha256(SPEC_PATH),
            corpus_sha256=sha256(CORPUS_PATH),
            source_files_verified=source_count,
            code_version=snapshot,
            page_order=[page["page"] for page in pages],
            discovery=list(base.DISCOVERY),
            holdout=list(base.HOLDOUT),
            excluded=["LP2/50"],
            views=list(base.VIEW_NAMES),
            field="F29",
            minimum_length=base.MIN_LENGTH,
            prefix_rule="floor(2N/3)",
            max_order_rule="min(16,floor(prefix_length/4))",
            controls=dict(
                count=CONTROL_COUNT,
                seed=CONTROL_SEED,
                null="within-page permutation before four views",
                replicate_rule="Random(CONTROL_SEED + replicate), replicate 0..998",
            ),
            alpha=ALPHA,
            tie_tolerance=TIE_TOLERANCE,
            wall_seconds=WALL_SECONDS,
            rune_count=sum(page["rune_count"] for page in applicable),
            gate=dict(positive_count=20, negative_count=99, seed=CONTROL_SEED),
            continuation=dict(
                source_run=SOURCE_RUN.relative_to(ROOT).as_posix(),
                source_partial_sha256=sha256(SOURCE_PARTIAL),
                source_record_sha256=sha256(SOURCE_RECORD),
                source_frozen_sha256=sha256(SOURCE_FROZEN),
                source_completed=RESUME_COUNT,
                next_replicate=RESUME_COUNT,
                final_replicate=CONTROL_COUNT - 1,
            ),
        )
        write_json(run / "frozen.json", frozen)
        prior_rows, resume_audit = validate_resume_rows(applicable)
        write_json(run / "resume-source.json", resume_audit)
        record.update(
            source_files_verified=source_count,
            frozen_sha256=sha256(run / "frozen.json"),
            resume_validation=resume_audit,
        )
        write_json(run / "record.json", record)

        gate_jobs, gate_private = base.make_gate()
        write_json(run / "verifier-only" / "gate-answers.json", gate_private)
        gate_output = run_worker(run, "gate", gate_jobs, started=started)
        gate = base.validate_gate(gate_output, gate_private)
        write_json(run / "gate.json", gate)
        record.update(
            gate_status=gate["status"],
            gate_positive_passes=gate["positive_passes"],
            gate_negative_false_accepts=gate["negative_false_accepts"],
        )
        write_json(run / "record.json", record)
        if gate["status"] != "passed":
            raise RuntimeError("H030-v3 power gate failed; LP2 is not interpreted")

        observed_output = run_worker(
            run,
            "formal-observed",
            [dict(id=page["page"], cipher=page["values"]) for page in applicable],
            started=started,
        )
        verification = base.validate_observed(observed_output, applicable)
        write_json(
            run / "independent-verification.json",
            {key: value for key, value in verification.items() if key != "metrics"},
        )
        observed_metrics = verification["metrics"]
        write_json(
            run / "observed.json",
            dict(pages=observed_metrics, page_order=[page["page"] for page in applicable]),
        )

        controls = list(prior_rows)
        write_json_atomic(run / "control-results.partial.json", controls)
        record["controls_completed"] = len(controls)
        save_checkpoint(run, run / "frozen.json", len(controls), "partial")
        write_json(run / "record.json", record)
        for replicate in range(RESUME_COUNT, CONTROL_COUNT):
            base.check_deadline(started)
            controlled, control_digest = base.make_control_values(applicable, replicate)
            row = dict(
                replicate=replicate,
                input_sha256=control_digest,
                pages={
                    page["page"]: base.compact_metrics(base.all_metrics(page["values"]))
                    for page in controlled
                },
            )
            controls.append(row)
            if (replicate + 1) % 25 == 0 or replicate + 1 == CONTROL_COUNT:
                write_json_atomic(run / "control-results.partial.json", controls)
                record["controls_completed"] = len(controls)
                save_checkpoint(run, run / "frozen.json", len(controls), "complete" if len(controls) == CONTROL_COUNT else "partial")
                write_json(run / "record.json", record)

        base.check_deadline(started)
        validate_control_rows(controls, applicable)
        write_json_atomic(run / "control-results.json", controls)
        summary = statistic_summary(observed_metrics, controls, applicable)
        write_json(run / "statistics.json", summary)
        record["controls_completed"] = len(controls)
        record.update(
            status=summary["status"],
            result=dict(leads=summary["leads"], strongest=summary["strongest"][:3]),
            actual_coverage=summary["coverage"],
        )
        elapsed_before = time.monotonic() - started
        if elapsed_before >= WALL_SECONDS:
            mark_deadline(run, run / "statistics.json", before=elapsed_before, after=None)
            raise TimeoutError(
                f"H030-v3 final deadline exceeded before source verification: {elapsed_before:.6f}s"
            )
        base.verify_sources(ROOT)
        elapsed_after = time.monotonic() - started
        if base.code_snapshot(ROOT) != snapshot:
            raise RuntimeError("code changed during H030-v3 run")
        audit = mark_deadline(
            run,
            run / "statistics.json",
            before=elapsed_before,
            after=elapsed_after,
        )
        record["deadline_check"] = audit
        if not audit["status"] == "passed":
            raise TimeoutError(
                f"H030-v3 final deadline exceeded after source verification: {elapsed_after:.6f}s"
            )
        record["accepted"] = True
        record["reproduction_bundle"] = base.archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
    except Exception as exc:
        record.update(
            status="timeout" if isinstance(exc, TimeoutError) else "error",
            error=repr(exc),
            finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            elapsed_seconds=time.monotonic() - started,
        )
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
        try:
            record["reproduction_bundle"] = base.archive_run(run, snapshot)
        except Exception as archive_exc:
            record["archive_error"] = repr(archive_exc)
    write_json(run / "record.json", record)
    print(
        json.dumps(
            {
                "run": run.relative_to(ROOT).as_posix(),
                "status": record["status"],
                "controls_completed": record.get("controls_completed", 0),
                "error": record.get("error"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
