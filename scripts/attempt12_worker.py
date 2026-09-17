"""Guarded H016 worker; stdin contains public ciphertext jobs only."""

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.periodic_f_state import scan_page


KEY = (0, 10, 4, 0, 1, 19, 0, 18, 4, 18, 9, 0, 18)
BRANCHES = ("continuous", "page_reset")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H016 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != "H016-periodic-plaintext-F-state-v1":
        raise ValueError("Unknown H016 experiment")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 10:
        raise ValueError("Invalid H016 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "branch", "pages"}:
            raise ValueError("Invalid H016 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H016 job id")
        if job["branch"] not in BRANCHES:
            raise ValueError("Unknown H016 continuity branch")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H016 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H016 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H016 page id")
            seen_pages.add(page["page"])
            cipher = page["cipher"]
            if not isinstance(cipher, list) or not cipher or any(
                type(value) is not int or not 0 <= value < 29 for value in cipher
            ):
                raise ValueError("Invalid H016 ciphertext")
            total += len(cipher)
        if total > 14_000:
            raise ValueError("H016 rune budget exceeded")
    return jobs


def run_job(job):
    states = (0,)
    rows = []
    for page in job["pages"]:
        starts = states if job["branch"] == "continuous" else (0,)
        result = scan_page(page["cipher"], start_phases=starts, key=KEY)
        result["page"] = page["page"]
        rows.append(result)
        if job["branch"] == "continuous":
            states = tuple(result["final_phases"])
    return {
        "id": job["id"],
        "branch": job["branch"],
        "pages": rows,
        "final_phases": sorted(states) if job["branch"] == "continuous" else None,
    }


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H016 worker read guard failed")
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
