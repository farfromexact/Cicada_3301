"""Run the strengthened H016-v3 validation batch.

The scientific model and LP2 statistic are unchanged from H016-v2.  This
wrapper replaces only the verifier-only positive jobs with genuine two-page
jobs and adds a final monotonic deadline audit to the v2 runner.
"""

from __future__ import annotations

from pathlib import Path
import datetime as dt
import json
import sys
import time

import attempt13_periodic_f_state_v2 as base


ROOT = Path(__file__).resolve().parents[1]
HYPOTHESIS = "H016-periodic-plaintext-F-state-v3"
SPEC_PATH = ROOT / "hypotheses/H016-periodic-plaintext-F-state-v3.json"
WORKER_PATH = ROOT / "scripts/attempt13_worker_v3.py"
CONTROL_SEED = 33011603
SYNTHETIC_SEED = 33011604
EXPECTED_POSITIVE_JOB_IDS = frozenset(
    {
        "synthetic-positive-1-continuous",
        "synthetic-positive-1-page_reset",
        "synthetic-positive-2-continuous",
        "synthetic-positive-2-page_reset",
    }
)
IMPOSSIBLE_JOB_ID = "incompatible-control-v3"


def _split(values, split=64):
    if len(values) != 128 or not 0 < split < len(values):
        raise ValueError("H016-v3 synthetic plans must split a 128-rune plaintext")
    return [list(values[:split]), list(values[split:])]


def _positive_job(base_name, branch, plaintext):
    plain_pages = _split(plaintext)
    cipher_pages = []
    traces = []
    expected_page_phases = []
    cumulative_plain = []
    cumulative_cipher = []

    if branch == "continuous":
        cipher, _, trace = base.encrypt_plain(plaintext)
        cipher_pages = _split(cipher)
        trace_pages = [trace[:64], trace[64:]]
        for plain_page, cipher_page, trace_page in zip(
            plain_pages, cipher_pages, trace_pages
        ):
            cumulative_plain.extend(plain_page)
            cumulative_cipher.extend(cipher_page)
            expected_page_phases.append(
                base.replay_expected(cumulative_cipher, cumulative_plain)
            )
            traces.append(trace_page)
    elif branch == "page_reset":
        for plain_page in plain_pages:
            cipher_page, endpoint, trace_page = base.encrypt_plain(plain_page)
            cipher_pages.append(cipher_page)
            expected_page_phases.append(endpoint)
            traces.append(trace_page)
    else:
        raise ValueError(f"Unknown H016-v3 branch: {branch}")

    job_id = f"{base_name}-{branch}"
    return (
        dict(
            id=job_id,
            branch=branch,
            pages=[
                dict(page=f"{base_name}-p{index + 1}", cipher=cipher_page)
                for index, cipher_page in enumerate(cipher_pages)
            ],
        ),
        dict(
            kind="positive",
            branch=branch,
            page_ids=[f"{base_name}-p1", f"{base_name}-p2"],
            plaintext_pages=plain_pages,
            expected_page_phases=expected_page_phases,
            expected_terminal_phase=expected_page_phases[-1],
            traces=traces,
            split_index=64,
            exception_positions=[
                row["position"]
                for trace in traces
                for row in trace
                if row["kind"] == "plaintext_f_exception"
            ],
            ordinary_ciphertext_f_positions=[
                row["position"]
                for trace in traces
                for row in trace
                if row["kind"] == "ordinary_ciphertext_f"
            ],
        ),
    )


def synthetic_controls(heldout):
    if len(heldout) < 256:
        raise ValueError("Heldout text is too short for H016-v3 synthetic controls")
    plans = [list(heldout[:128])]
    plans[0][0] = 0
    plans[0][1] = 1
    plans[0][2] = (-base.DEFAULT_KEY[1]) % 29
    rng = __import__("random").Random(SYNTHETIC_SEED)
    random_plain = [rng.randrange(29) for _ in range(128)]
    random_plain[0] = 0
    random_plain[1] = 1
    random_plain[2] = (-base.DEFAULT_KEY[1]) % 29
    random_plain[17] = 0
    random_plain[64] = 0
    plans.append(random_plain)

    jobs = []
    answers = {}
    for index, plaintext in enumerate(plans):
        base_name = f"synthetic-positive-{index + 1}"
        for branch in base.BRANCHES:
            job, answer = _positive_job(base_name, branch, plaintext)
            jobs.append(job)
            answers[job["id"]] = answer
    jobs.append(
        dict(
            id=IMPOSSIBLE_JOB_ID,
            branch="page_reset",
            pages=[dict(page=IMPOSSIBLE_JOB_ID, cipher=[1, base.DEFAULT_KEY[1]])],
        )
    )
    answers[IMPOSSIBLE_JOB_ID] = dict(kind="incompatible")
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS | {IMPOSSIBLE_JOB_ID}:
        raise ValueError("H016-v3 synthetic answer/job registration drifted")
    return jobs, answers


def verify_worker(public, output, answers):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"}:
        raise ValueError("Unexpected H016-v3 worker output fields")
    if output["status"] != "completed" or not output.get("read_guard_probe_passed"):
        raise ValueError("H016-v3 worker did not complete under its read guard")
    public_ids = [job["id"] for job in public["jobs"]]
    if [job["id"] for job in output.get("jobs", [])] != public_ids:
        raise ValueError("H016-v3 worker omitted or reordered jobs")
    if set(answers) != EXPECTED_POSITIVE_JOB_IDS | {IMPOSSIBLE_JOB_ID}:
        raise ValueError("Private H016-v3 answer map is incomplete")

    path_checks = []
    page_endpoint_checks = []
    impossible_checks = []
    for public_job, output_job in zip(public["jobs"], output["jobs"]):
        job_id = public_job["id"]
        if output_job.get("id") != job_id or output_job.get("branch") != public_job["branch"]:
            raise ValueError("H016-v3 worker job identity mismatch")
        expected = base.independent_job(public_job)
        if [row["page"] for row in output_job["pages"]] != [
            row["page"] for row in expected["pages"]
        ]:
            raise ValueError(f"H016-v3 worker page coverage mismatch: {job_id}")
        for actual, expected_row in zip(output_job["pages"], expected["pages"]):
            if any(
                actual.get(field) != expected_row[field]
                for field in base.SUMMARY_FIELDS
            ):
                raise ValueError(
                    f"Independent H016-v3 state check failed: {job_id}/{actual['page']}"
                )
        if output_job.get("final_phases") != expected["final_phases"]:
            raise ValueError(f"H016-v3 worker final phase mismatch: {job_id}")
        if output_job.get("final_path_counts") != expected["final_path_counts"]:
            raise ValueError(f"H016-v3 worker final path-count mismatch: {job_id}")

        answer = answers.get(job_id, {})
        if answer.get("kind") == "positive":
            plain_pages = answer["plaintext_pages"]
            if len(public_job["pages"]) != 2 or len(plain_pages) != 2:
                raise ValueError(f"H016-v3 positive is not genuinely two-page: {job_id}")
            if [page["page"] for page in public_job["pages"]] != answer["page_ids"]:
                raise ValueError(f"H016-v3 positive page IDs changed: {job_id}")
            if [len(page["cipher"]) for page in public_job["pages"]] != [
                len(page) for page in plain_pages
            ]:
                raise ValueError(f"H016-v3 positive page lengths changed: {job_id}")
            expected_endpoints = answer["expected_page_phases"]
            if public_job["branch"] == "continuous":
                cumulative_cipher = []
                cumulative_plain = []
                for index, (page, plain_page, expected_endpoint) in enumerate(
                    zip(public_job["pages"], plain_pages, expected_endpoints)
                ):
                    cumulative_cipher.extend(page["cipher"])
                    cumulative_plain.extend(plain_page)
                    endpoint = base.replay_expected(cumulative_cipher, cumulative_plain)
                    if endpoint != expected_endpoint:
                        raise ValueError(
                            f"H016-v3 cumulative endpoint construction failed: {job_id}/{index}"
                        )
            else:
                for index, (page, plain_page, expected_endpoint) in enumerate(
                    zip(public_job["pages"], plain_pages, expected_endpoints)
                ):
                    endpoint = base.replay_expected(page["cipher"], plain_page)
                    if endpoint != expected_endpoint:
                        raise ValueError(
                            f"H016-v3 page-reset endpoint construction failed: {job_id}/{index}"
                        )
            if public_job["branch"] == "continuous":
                cumulative_cipher = []
                cumulative_plain = []
                for page, plain_page, expected_endpoint, row in zip(
                    public_job["pages"],
                    plain_pages,
                    expected_endpoints,
                    output_job["pages"],
                ):
                    cumulative_cipher.extend(page["cipher"])
                    cumulative_plain.extend(plain_page)
                    endpoint = base.replay_expected(cumulative_cipher, cumulative_plain)
                    if endpoint != expected_endpoint or endpoint not in row["final_phases"]:
                        raise ValueError(
                            f"H016-v3 continuous endpoint is unreachable: {job_id}"
                        )
                    page_endpoint_checks.append(
                        dict(job=job_id, page=row["page"], endpoint_phase=endpoint)
                    )
                if output_job["final_phases"] is None or (
                    expected_endpoints[-1] not in output_job["final_phases"]
                ):
                    raise ValueError(f"H016-v3 continuous terminal endpoint missing: {job_id}")
            else:
                for row, expected_endpoint in zip(
                    output_job["pages"], expected_endpoints
                ):
                    if expected_endpoint not in row["final_phases"]:
                        raise ValueError(f"H016-v3 page endpoint is unreachable: {job_id}")
                    page_endpoint_checks.append(
                        dict(
                            job=job_id,
                            page=row["page"],
                            endpoint_phase=expected_endpoint,
                        )
                    )
            if any(row["terminal_path_count_capped"] < 1 for row in output_job["pages"]):
                raise ValueError(f"H016-v3 positive has no terminal path: {job_id}")
            path_checks.append(
                dict(
                    job=job_id,
                    pages=2,
                    endpoint_phase=expected_endpoints[-1],
                    expected_page_phases=expected_endpoints,
                )
            )

        if job_id == IMPOSSIBLE_JOB_ID:
            row = output_job["pages"][0]
            if row["model_status"] != "dead" or row["final_state_count"] != 0:
                raise ValueError("H016-v3 incompatible control remained reachable")
            if row["first_dead_position"] != 1:
                raise ValueError("H016-v3 incompatible-control death position changed")
            impossible_checks.append(dict(job=job_id, status="negative"))

    if {row["job"] for row in path_checks} != EXPECTED_POSITIVE_JOB_IDS or len(path_checks) != 4:
        raise ValueError("H016-v3 positive validation is incomplete")
    if len(page_endpoint_checks) != 8:
        raise ValueError("H016-v3 page endpoint validation is incomplete")
    if len(impossible_checks) != 1:
        raise ValueError("H016-v3 incompatible-control validation is incomplete")
    return dict(
        status="passed",
        worker_jobs=len(public["jobs"]),
        public_sha256=base.stable_digest(public),
        positive_path_checks=path_checks,
        positive_page_endpoint_checks=page_endpoint_checks,
        incompatible_checks=impossible_checks,
        independent_algorithm="forward-enumerated 13x29 transition table plus capped path recurrence; endpoints checked page-by-page",
    )


_original_verify_sources = base.verify_sources
_v3_started = None
_v3_run = None


def verify_sources_with_deadline(root):
    statistics = _v3_run / "statistics.json" if _v3_run is not None else None
    before = None
    if _v3_started is not None and statistics is not None and statistics.exists():
        before = time.monotonic() - _v3_started
        if before >= base.WALL_SECONDS:
            _mark_deadline(statistics, before=before, after=None, accepted=False)
            raise TimeoutError(
                f"H016-v3 final deadline exceeded before source verification: {before:.6f}s"
            )

    result = _original_verify_sources(root)
    if _v3_started is not None and statistics is not None and statistics.exists():
        after = time.monotonic() - _v3_started
        accepted = after < base.WALL_SECONDS
        _mark_deadline(statistics, before=before, after=after, accepted=accepted)
        if not accepted:
            raise TimeoutError(
                f"H016-v3 final deadline exceeded after source verification: {after:.6f}s"
            )
    return result


def _mark_deadline(statistics, *, before, after, accepted):
    audit = dict(
        schema=1,
        status="passed" if accepted else "timeout",
        stage="after_statistics_before_and_after_final_source_verification",
        before_seconds=before,
        after_seconds=after,
        wall_seconds=base.WALL_SECONDS,
        checked_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    summary = json.loads(statistics.read_text(encoding="utf8"))
    summary["accepted"] = accepted
    summary["deadline_check"] = audit
    statistics.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf8",
    )
    (_v3_run / "deadline-check.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf8",
    )


def main():
    global _v3_started, _v3_run
    if "--out" not in sys.argv:
        raise ValueError("H016-v3 requires --out")
    _v3_run = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    _v3_started = time.monotonic()

    base.HYPOTHESIS = HYPOTHESIS
    base.SPEC_PATH = SPEC_PATH
    base.WORKER_PATH = WORKER_PATH
    base.CONTROL_SEED = CONTROL_SEED
    base.SYNTHETIC_SEED = SYNTHETIC_SEED
    base.EXPECTED_POSITIVE_JOB_IDS = EXPECTED_POSITIVE_JOB_IDS
    base.IMPOSSIBLE_JOB_ID = IMPOSSIBLE_JOB_ID
    base.synthetic_controls = synthetic_controls
    base.verify_worker = verify_worker
    base.verify_sources = verify_sources_with_deadline
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
