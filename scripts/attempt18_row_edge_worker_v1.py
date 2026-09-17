"""Guarded H023 worker for fixed row edge/interior G statistics."""

from pathlib import Path
import json
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.runes import RUNES


HYPOTHESIS = "H023-row-edge-interior-g-v1"
RUNE_TO_INDEX = {char: index for index, char in enumerate(RUNES)}
SOFT_SEPARATORS = frozenset("-.,")
PAGE_FIELDS = ("page", "rows", "eligible_row_count", "edge_count", "interior_count", "g_stat")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H023 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H023 job schema")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 180:
        raise ValueError("Invalid H023 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"}:
            raise ValueError("Invalid H023 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H023 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H023 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "raw"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H023 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H023 page id")
            seen_pages.add(page["page"])
            raw = page["raw"]
            if not isinstance(raw, str) or not raw or len(raw) > 20_000:
                raise ValueError("Invalid H023 raw page")
            total += len(raw)
        if total > 40_000:
            raise ValueError("H023 raw-page budget exceeded")
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


def g_statistic(rows):
    counts = [[0, 0] for _ in range(29)]
    eligible_row_count = 0
    edge_count = 0
    interior_count = 0
    for row in rows:
        if row["rune_count"] < 3 or row["group"] is None:
            continue
        eligible_row_count += 1
        edge_values = (row["values"][0], row["values"][-1])
        interior_values = row["values"][1:-1]
        for value in edge_values:
            counts[value][0] += 1
        for value in interior_values:
            counts[value][1] += 1
        edge_count += len(edge_values)
        interior_count += len(interior_values)
    total = edge_count + interior_count
    if total == 0:
        statistic = None
    else:
        row_totals = [sum(columns) for columns in counts]
        column_totals = [sum(counts[row][column] for row in range(29)) for column in range(2)]
        statistic = 0.0
        for row in range(29):
            for column in range(2):
                observed = counts[row][column]
                expected = row_totals[row] * column_totals[column] / total
                if observed:
                    statistic += 2.0 * observed * math.log(observed / expected)
    return dict(
        eligible_row_count=eligible_row_count,
        edge_count=edge_count,
        interior_count=interior_count,
        g_stat=statistic,
    )


def run_job(job):
    pages = []
    for page in job["pages"]:
        rows = rows_from_raw(page["raw"])
        pages.append(dict(page=page["page"], rows=rows, **g_statistic(rows)))
    return dict(id=job["id"], pages=pages)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H023 worker read guard failed")
    public = json.loads(sys.stdin.read())
    jobs = validate_public(public)
    output = dict(status="completed", read_guard_probe_passed=guarded, jobs=[run_job(job) for job in jobs])
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
