"""Guarded H022 worker for fixed alternating row reversal."""

from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.runes import RUNES


HYPOTHESIS = "H022-snake-row-bigram-v1"
RUNE_TO_INDEX = {char: index for index, char in enumerate(RUNES)}
SOFT_SEPARATORS = frozenset("-.,")
VECTOR_SIZE = 29 * 29


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("H022 worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Unknown H022 job schema")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 180:
        raise ValueError("Invalid H022 job count")
    seen_jobs = set()
    for job in jobs:
        if set(job) != {"id", "pages"}:
            raise ValueError("Invalid H022 job fields")
        if not isinstance(job["id"], str) or job["id"] in seen_jobs:
            raise ValueError("Duplicate H022 job id")
        seen_jobs.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("Invalid H022 page batch")
        seen_pages = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "raw"} or not isinstance(page["page"], str):
                raise ValueError("Invalid H022 page fields")
            if page["page"] in seen_pages:
                raise ValueError("Duplicate H022 page id")
            seen_pages.add(page["page"])
            raw = page["raw"]
            if not isinstance(raw, str) or not raw or len(raw) > 20_000:
                raise ValueError("Invalid H022 raw page")
            total += len(raw)
        if total > 40_000:
            raise ValueError("H022 raw-page budget exceeded")
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


def _eligible(row):
    return row["rune_count"] >= 2 and row["group"] is not None


def snake_mask(rows):
    mask = [False] * len(rows)
    parity = 0
    previous = None
    for index, row in enumerate(rows):
        if not _eligible(row):
            parity = 0
            previous = None
            continue
        if previous is None or previous != index - 1 or rows[previous]["group"] != row["group"]:
            parity = 0
        mask[index] = parity % 2 == 1
        parity += 1
        previous = index
    return mask


def _vector(values):
    if len(values) < 2:
        return None
    counts = [0] * VECTOR_SIZE
    for left, right in zip(values, values[1:]):
        counts[left * 29 + right] += 1
    divisor = len(values) - 1
    return [count / divisor for count in counts]


def _score(rows, mask):
    vectors = []
    for row, reverse in zip(rows, mask):
        values = list(reversed(row["values"])) if reverse else row["values"]
        vectors.append(_vector(values))
    pair_scores = []
    for index, (left, right) in enumerate(zip(rows, rows[1:])):
        if not _eligible(left) or not _eligible(right) or left["group"] != right["group"]:
            continue
        pair_scores.append(sum(a * b for a, b in zip(vectors[index], vectors[index + 1])))
    return sum(pair_scores) / len(pair_scores) if pair_scores else None, len(pair_scores)


def run_job(job):
    pages = []
    for page in job["pages"]:
        rows = rows_from_raw(page["raw"])
        original_score, pair_count = _score(rows, [False] * len(rows))
        snake_score, snake_pair_count = _score(rows, snake_mask(rows))
        if pair_count != snake_pair_count:
            raise ValueError("H022 orientation changed legal pair coverage")
        pages.append(
            dict(
                page=page["page"],
                rows=rows,
                original_score=original_score,
                snake_score=snake_score,
                delta=(snake_score - original_score if snake_score is not None else None),
                pair_count=pair_count,
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
        raise RuntimeError("H022 worker read guard failed")
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
