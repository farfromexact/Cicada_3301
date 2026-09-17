"""Guarded H016-v2 worker; stdin contains public ciphertext jobs only."""

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.periodic_f_state_v2 import DEFAULT_KEY, scan_page


KEY = DEFAULT_KEY
BRANCHES = ("continuous", "page_reset")
HYPOTHESIS = "H016-periodic-plaintext-F-state-v2"


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H016-v2 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H016-v2 experiment")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 10:
        raise ValueError("Invalid H016-v2 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "branch", "pages"}:
            raise ValueError("Invalid H016-v2 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H016-v2 job id")
        if job["branch"] not in BRANCHES:
            raise ValueError("Unknown H016-v2 continuity branch")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H016-v2 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H016-v2 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H016-v2 page id")
            seen_pages.add(page["page"])
            cipher = page["cipher"]
            if not isinstance(cipher, list) or not cipher or any(
                type(value) is not int or not 0 <= value < 29 for value in cipher
            ):
                raise ValueError("Invalid H016-v2 ciphertext")
            total += len(cipher)
        if total > 14_000:
            raise ValueError("H016-v2 rune budget exceeded")
    return jobs


def _not_reached(cipher, page, upstream_dead_page):
    result = scan_page(cipher, start_phases=(), initial_ways={}, key=KEY)
    result.update(
        page=page,
        model_status="not_reached",
        upstream_dead_page=upstream_dead_page,
        not_reached_reason="continuous_prefix_state_empty",
        first_dead_position=None,
        legal_prefix_length=None,
        legal_prefix_ratio=None,
    )
    return result


def run_job(job):
    states = (0,)
    ways = {0: 1}
    rows = []
    upstream_dead_page = None
    for page in job["pages"]:
        if job["branch"] == "continuous" and not states:
            rows.append(_not_reached(page["cipher"], page["page"], upstream_dead_page))
            continue
        starts = states if job["branch"] == "continuous" else (0,)
        initial_ways = ways if job["branch"] == "continuous" else {0: 1}
        result = scan_page(
            page["cipher"], start_phases=starts, initial_ways=initial_ways, key=KEY
        )
        result.update(
            page=page["page"],
            model_status="compatible" if result["final_state_count"] else "dead",
            upstream_dead_page=None,
            not_reached_reason=None,
        )
        rows.append(result)
        if job["branch"] == "continuous":
            states = tuple(result["final_phases"])
            ways = {phase: count for phase, count in result["final_path_counts"]}
            if not states:
                upstream_dead_page = page["page"]
    return {
        "id": job["id"],
        "branch": job["branch"],
        "pages": rows,
        "final_phases": sorted(states) if job["branch"] == "continuous" else None,
        "final_path_counts": (
            [[phase, ways[phase]] for phase in sorted(ways)]
            if job["branch"] == "continuous"
            else None
        ),
    }


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H016-v2 worker read guard failed")
    public = json.loads(sys.stdin.read())
    jobs = validate_public(public)
    output = {
        "status": "completed",
        "read_guard_probe_passed": guarded,
        "jobs": [run_job(job) for job in jobs],
    }
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
