"""Guarded H025 worker; stdin contains only public ciphertext pages."""

import json
import sys


HYPOTHESIS = "H025-plaintext-feedback-v1"
PAGE_FIELDS = ("page", "rune_count", "decoded_indices", "initial_previous_plain")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H025 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected H025 public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H025 experiment")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 120:
        raise ValueError("Invalid H025 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"}:
            raise ValueError("Invalid H025 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H025 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H025 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H025 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H025 page id")
            seen_pages.add(page["page"])
            cipher = page["cipher"]
            if not isinstance(cipher, list) or not cipher or any(
                type(value) is not int or not 0 <= value < 29 for value in cipher
            ):
                raise ValueError("Invalid H025 ciphertext")
            total += len(cipher)
        if total > 14_000:
            raise ValueError("H025 rune budget exceeded")
    return jobs


def decode_plaintext_feedback(cipher):
    """Decode P[i]=(C[i]-P[i-1]) mod29 with P[-1]=0."""
    previous_plain = 0
    decoded = []
    for value in cipher:
        next_plain = (value - previous_plain) % 29
        decoded.append(next_plain)
        previous_plain = next_plain
    return decoded


def run_job(job):
    pages = []
    for page in job["pages"]:
        decoded = decode_plaintext_feedback(page["cipher"])
        pages.append(
            dict(
                page=page["page"],
                rune_count=len(page["cipher"]),
                decoded_indices=decoded,
                initial_previous_plain=0,
            )
        )
    return dict(id=job["id"], pages=pages)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H025 worker read guard failed")
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
