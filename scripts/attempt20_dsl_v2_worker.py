"""Guarded R015-A DSL worker; all input arrives as public JSON on stdin."""

import json
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.r015_dsl_v2 import MAX_DEPTH, STATE_OPERATORS, best_program, enumerate_recipes


HYPOTHESIS = "H029-finite-dsl-v2"


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("R015-A worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "programs", "model", "jobs"}:
        raise ValueError("R015-A public input contains an answer, seed or unexpected field")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("unexpected R015-A hypothesis")
    programs = public["programs"]
    expected, _ = enumerate_recipes(MAX_DEPTH)
    if programs != [list(program) for program in expected]:
        raise ValueError("program universe is not the frozen source-independent universe")
    model = public["model"]
    if set(model) != {"start_weights", "transition_weights"}:
        raise ValueError("unexpected public model fields")
    if len(model["start_weights"]) != 29 or len(model["transition_weights"]) != 29:
        raise ValueError("invalid 29-symbol model")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 120:
        raise ValueError("invalid R015-A job count")
    seen = set()
    total = 0
    for job in jobs:
        if set(job) != {"id", "pages"} or not isinstance(job["id"], str):
            raise ValueError("invalid R015-A job fields")
        if job["id"] in seen:
            raise ValueError("duplicate R015-A job")
        seen.add(job["id"])
        pages = job["pages"]
        if not isinstance(pages, list) or not pages:
            raise ValueError("invalid R015-A page batch")
        for page in pages:
            if set(page) != {"page", "cipher"} or not isinstance(page["page"], str):
                raise ValueError("invalid R015-A page fields")
            values = page["cipher"]
            if not isinstance(values, list) or not values or any(
                type(value) is not int or not 0 <= value < 29 for value in values
            ):
                raise ValueError("invalid R015-A rune stream")
            total += len(values)
    if total > 80000:
        raise ValueError("R015-A rune budget exceeded")
    return programs, model, jobs


def main():
    sys.addaudithook(guard)
    try:
        open("__r015_a_forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("R015-A read guard failed")
    public = json.loads(sys.stdin.read())
    programs, model, jobs = validate_public(public)
    results = []
    for job in jobs:
        page_rows = []
        for page in job["pages"]:
            scored = best_program(page["cipher"], [tuple(p) for p in programs], model)
            page_rows.append(dict(page=page["page"], selected=scored["selected"],
                                  rankings=scored["rankings"]))
        aggregate = []
        for index, program in enumerate(programs):
            values = [next(item["score"] for item in row["rankings"]
                           if item["program"] == program) for row in page_rows]
            aggregate.append(dict(program=program, depth=len(program),
                                  score=(float("-inf") if any(value == float("-inf") for value in values)
                                         else sum(values) / len(values)),
                                  page_scores=values))
        aggregate.sort(key=lambda row: (-row["score"], row["depth"], row["program"]))
        results.append(dict(id=job["id"], selected=aggregate[0], rankings=aggregate,
                            page_results=page_rows))
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded,
                          job_count=len(results), results=results),
                     ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
