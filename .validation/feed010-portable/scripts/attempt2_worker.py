"""Fixed known-page transforms; source parameters public, references inaccessible."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.skip_mechanics import transform as skip_transform
from lp_lab.boundary_clock import transform as boundary_transform


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(("socket.", "subprocess.", "ctypes.")):
        raise PermissionError("Known-page worker denies file/process/network reads")


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("Read guard failed")
    public = json.loads(sys.stdin.read())
    if set(public) != {"schema", "experiment", "jobs"} or public["schema"] != 1 or public["experiment"] != "attempt2-mechanics-v1":
        raise ValueError("Unexpected public fields; no expected answers or seeds")
    if not 1 <= len(public["jobs"]) <= 26:
        raise ValueError("Known-configuration budget exceeded")
    results = []
    for job in public["jobs"]:
        if set(job) != {"id", "kind", "pages", "parameters"}:
            raise ValueError("Unexpected job fields")
        if any(set(p) != {"page", "raw"} for p in job["pages"]):
            raise ValueError("Unexpected page fields")
        if job["kind"] == "skip":
            allowed = {"mode", "direction", "policy", "continuity", "specified_skip", "key"}
            if set(job["parameters"]) != allowed:
                raise ValueError("Unexpected skip parameters")
            result = skip_transform(job["pages"], **job["parameters"])
        elif job["kind"] == "boundary":
            if set(job["parameters"]) != {"branch", "skip_ordinal", "title_boundary", "hash_spans"} or len(job["pages"]) != 1:
                raise ValueError("Unexpected boundary parameters")
            result = boundary_transform(job["pages"][0]["raw"], **job["parameters"])
            result["pages"] = [dict(page=job["pages"][0]["page"], raw=result["raw"], indices=result["indices"])]
        else:
            raise ValueError("Unknown job kind")
        results.append(dict(id=job["id"], result=result))
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded, cases=len(results), results=results), ensure_ascii=True))


if __name__ == "__main__":
    main()
