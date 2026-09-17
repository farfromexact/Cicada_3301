"""Guarded R015-B worker; BM receives only public sequences and view names."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.r015_bm import metrics, views


HYPOTHESIS = "H030-berlekamp-massey-v1"
VIEW_NAMES = ("raw", "difference", "gp_projection", "gp_totient_projection",
              "position_prime_residual", "position_totient_residual")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(
        ("socket.", "subprocess.", "ctypes.")
    ):
        raise PermissionError("R015-B worker denies file/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "jobs"}:
        raise ValueError("R015-B public input contains an answer, seed or unexpected field")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("unexpected R015-B hypothesis")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 60:
        raise ValueError("invalid R015-B job count")
    seen = set()
    total = 0
    for job in jobs:
        if set(job) != {"id", "cipher"} or not isinstance(job["id"], str):
            raise ValueError("invalid R015-B job fields")
        if job["id"] in seen:
            raise ValueError("duplicate R015-B job")
        seen.add(job["id"])
        values = job["cipher"]
        if not isinstance(values, list) or not values or any(
            type(value) is not int or not 0 <= value < 29 for value in values
        ):
            raise ValueError("invalid R015-B sequence")
        total += len(values)
    if total > 16000:
        raise ValueError("R015-B rune budget exceeded")
    return jobs


def main():
    sys.addaudithook(guard)
    try:
        open("__r015_b_forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("R015-B read guard failed")
    jobs = validate_public(json.loads(sys.stdin.read()))
    results = []
    for job in jobs:
        source_views = views(job["cipher"])
        rows = {name: metrics(source_views[name]) for name in VIEW_NAMES}
        results.append(dict(id=job["id"], sequence_length=len(job["cipher"]), views=rows))
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded,
                          view_names=list(VIEW_NAMES), results=results),
                     ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
