"""Guarded H007 finite-state scan; stdin is the only input channel."""

import json
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.reachability import prime_deltas, scan_cipher


CONTINUITIES = ("continuous", "page_reset")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H007 worker denies file/process/network access")


def _validate(public):
    if set(public) != {"schema", "hypothesis", "continuities", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != "H007-v1":
        raise ValueError("Unknown experiment")
    if tuple(public["continuities"]) != CONTINUITIES:
        raise ValueError("H007 continuity branches are frozen")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 16:
        raise ValueError("Invalid H007 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"} or not isinstance(job["id"], str):
            raise ValueError("Invalid H007 job fields")
        if job["id"] in seen_jobs:
            raise ValueError("Duplicate H007 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H007 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H007 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H007 page id")
            seen_pages.add(page["page"])
            cipher = page["cipher"]
            if not isinstance(cipher, list) or not cipher or any(
                type(value) is not int or not 0 <= value < 29 for value in cipher
            ):
                raise ValueError("Invalid H007 ciphertext")
            total += len(cipher)
        if total > 14_000:
            raise ValueError("H007 rune budget exceeded")
    return jobs


def _run_branch(pages, continuity, deltas):
    state = (0,)
    rows = []
    for page in pages:
        starts = state if continuity == "continuous" else (0,)
        result = scan_cipher(page["cipher"], start_clocks=starts, deltas=deltas)
        result["page"] = page["page"]
        rows.append(result)
        if continuity == "continuous":
            state = tuple(result["final_clocks"])
    return dict(
        continuity=continuity,
        pages=rows,
        final_clocks=sorted(state) if continuity == "continuous" else None,
    )


def run(public):
    jobs = _validate(public)
    outputs = []
    for job in jobs:
        total = sum(len(page["cipher"]) for page in job["pages"])
        deltas = prime_deltas(total)
        branches = {
            continuity: _run_branch(job["pages"], continuity, deltas)
            for continuity in CONTINUITIES
        }
        outputs.append(dict(id=job["id"], total_runes=total, branches=branches))
    return dict(status="completed", jobs=outputs)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("Read guard failed")
    output = run(json.loads(sys.stdin.read()))
    output["read_guard_probe_passed"] = guarded
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
