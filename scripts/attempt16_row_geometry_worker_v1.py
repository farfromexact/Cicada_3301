"""Guarded H021 worker for slash-delimited row geometry."""

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.runes import RUNES


HYPOTHESIS = "H021-row-alignment-geometry-v1"
RUNE_TO_INDEX = {char: index for index, char in enumerate(RUNES)}
SOFT_SEPARATORS = frozenset("-.,")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H021 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H021 job schema")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 180:
        raise ValueError("Invalid H021 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"}:
            raise ValueError("Invalid H021 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H021 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H021 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "raw"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H021 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H021 page id")
            seen_pages.add(page["page"])
            raw = page["raw"]
            if not isinstance(raw, str) or not raw or len(raw) > 20_000:
                raise ValueError("Invalid H021 raw page")
            total += len(raw)
        if total > 40_000:
            raise ValueError("H021 raw-page budget exceeded")
    return jobs


def _finish_row(rows, values, groups, row_number):
    rows.append(
        dict(
            row=row_number,
            group=next(iter(groups)) if len(groups) == 1 and values else None,
            values=list(values),
            rune_count=len(values),
        )
    )


def rows_from_raw(raw):
    rows = []
    values = []
    groups = set()
    hard_segment = 0
    pending_hard = False
    for char in raw:
        if char in RUNE_TO_INDEX:
            if pending_hard:
                hard_segment += 1
                pending_hard = False
            values.append(RUNE_TO_INDEX[char])
            groups.add(hard_segment)
        elif char == "/":
            _finish_row(rows, values, groups, len(rows))
            values = []
            groups = set()
        elif char in SOFT_SEPARATORS or char.isspace():
            continue
        else:
            if 0x16A0 <= ord(char) <= 0x16FF:
                raise ValueError("Unregistered runic glyph in public raw page")
            pending_hard = True
    if values:
        _finish_row(rows, values, groups, len(rows))
    return rows


def page_metrics(rows):
    equal_count = 0
    comparison_count = 0
    for left, right in zip(rows, rows[1:]):
        if not left["rune_count"] or not right["rune_count"]:
            continue
        if left["group"] is None or right["group"] != left["group"]:
            continue
        width = min(left["rune_count"], right["rune_count"])
        comparison_count += width
        equal_count += sum(
            a == b for a, b in zip(left["values"][:width], right["values"][:width])
        )
    return dict(
        equal_count=equal_count,
        comparison_count=comparison_count,
        score=(equal_count / comparison_count if comparison_count else None),
    )


def run_job(job):
    output_pages = []
    for page in job["pages"]:
        rows = rows_from_raw(page["raw"])
        output_pages.append(
            dict(
                page=page["page"],
                rows=rows,
                **page_metrics(rows),
            )
        )
    return dict(id=job["id"], pages=output_pages)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H021 worker read guard failed")
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
