"""Guarded R015-C worker; enumerates every public PGL representative."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.r015_pgl import INFINITY, mapping, matrices, score_counts


HYPOTHESIS = "H031-pgl-full-v1"


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("R015-C worker denies file/process/network access")


def validate_public(public):
    if set(public) not in ({"schema", "hypothesis", "model", "pages"},
                           {"schema", "hypothesis", "model", "jobs"}):
        raise ValueError("R015-C public input contains an answer, seed or unexpected field")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("unexpected R015-C hypothesis")
    model = public["model"]
    if set(model) != {"start_weights", "transition_weights"}:
        raise ValueError("unexpected public model fields")
    if len(model["start_weights"]) != INFINITY + 1 or len(model["transition_weights"]) != INFINITY + 1:
        raise ValueError("invalid 30-symbol model")
    batches = ([dict(id="formal", pages=public["pages"])] if "pages" in public
               else public["jobs"])
    if not isinstance(batches, list) or not 1 <= len(batches) <= 120:
        raise ValueError("invalid R015-C batch count")
    seen_batches = set()
    for batch in batches:
        if set(batch) != {"id", "pages"} or not isinstance(batch["id"], str):
            raise ValueError("invalid R015-C batch fields")
        if batch["id"] in seen_batches:
            raise ValueError("duplicate R015-C batch")
        seen_batches.add(batch["id"])
        pages = batch["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 60:
            raise ValueError("invalid R015-C page count")
        seen = set()
        total = 0
        for page in pages:
            if set(page) != {"page", "counts"} or not isinstance(page["page"], str):
                raise ValueError("invalid R015-C page fields")
            if page["page"] in seen:
                raise ValueError("duplicate R015-C page")
            seen.add(page["page"])
            counts = page["counts"]
            if set(counts) != {"starts", "transitions", "points"}:
                raise ValueError("invalid R015-C counts")
            if len(counts["starts"]) != 30 or len(counts["transitions"]) != 30:
                raise ValueError("invalid R015-C count dimensions")
            if any(type(value) is not int or value < 0 for value in counts["starts"]):
                raise ValueError("invalid R015-C start count")
            if any(len(row) != 30 or any(type(value) is not int or value < 0 for value in row)
                   for row in counts["transitions"]):
                raise ValueError("invalid R015-C transition count")
            if type(counts["points"]) is not int or counts["points"] <= 0:
                raise ValueError("invalid R015-C point count")
            total += counts["points"]
        if total > 30000:
            raise ValueError("R015-C point budget exceeded")
    return model, batches


def score_page(table, page, model):
    return score_counts(table, (page["counts"]["starts"], page["counts"]["transitions"],
                                page["counts"]["points"]), model)


def main():
    sys.addaudithook(guard)
    try:
        open("__r015_c_forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("R015-C read guard failed")
    model, batches = validate_public(json.loads(sys.stdin.read()))
    representatives = matrices()
    batch_results = []
    for batch in batches:
        rows = []
        for matrix in representatives:
            table = mapping(matrix)
            page_scores = [score_page(table, page, model) for page in batch["pages"]]
            rows.append((sum(page_scores) / len(page_scores), matrix, table, page_scores))
        rows.sort(key=lambda row: (-row[0], row[1]))
        best_score, best_matrix, best_table, page_scores = rows[0]
        ties = sum(abs(row[0] - best_score) <= 1e-12 for row in rows)
        batch_results.append(dict(id=batch["id"], matrix_count=len(rows),
                          selected=dict(matrix=list(best_matrix), mapping=list(best_table),
                                        score=best_score, ties=ties),
                          top=[dict(matrix=list(matrix), score=score, mapping=list(table))
                               for score, matrix, table, _ in rows[:8]],
                          selected_page_scores=page_scores))
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded,
                          matrix_count=len(representatives), results=batch_results),
                     ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
