"""Guarded H017 worker; stdin contains public ciphertext pages only."""

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.feedback import difference_page


HYPOTHESIS = "H017-ciphertext-feedback-v1"


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H017 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H017 experiment")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 10:
        raise ValueError("Invalid H017 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"}:
            raise ValueError("Invalid H017 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H017 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H017 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H017 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H017 page id")
            seen_pages.add(page["page"])
            cipher = page["cipher"]
            if not isinstance(cipher, list) or not cipher or any(
                type(value) is not int or not 0 <= value < 29 for value in cipher
            ):
                raise ValueError("Invalid H017 ciphertext")
            total += len(cipher)
        if total > 14_000:
            raise ValueError("H017 rune budget exceeded")
    return jobs


def run_job(job):
    rows = []
    for page in job["pages"]:
        decoded = difference_page(page["cipher"])
        rows.append(
            dict(
                page=page["page"],
                rune_count=len(page["cipher"]),
                decoded_indices=decoded,
                initial_previous_cipher=0,
            )
        )
    return dict(id=job["id"], pages=rows)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H017 worker read guard failed")
    public = json.loads(sys.stdin.read())
    jobs = validate_public(public)
    output = dict(
        status="completed",
        read_guard_probe_passed=guarded,
        jobs=[run_job(job) for job in jobs],
    )
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
