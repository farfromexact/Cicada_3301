"""Public-only optimized PGL gate. Load code/libraries before denying I/O."""
import json
import math
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.r015_pgl_v2 import matrices, mapping
sys.path.insert(0, str(ROOT / "scripts"))
from attempt22_pgl_v2_worker import guard, validate_public

HYPOTHESIS = "H031-pgl-power-gate-v3"

def select(scores, reps):
    maximum = float(np.max(scores))
    tied = np.flatnonzero(np.abs(scores - maximum) <= 1e-12).tolist()
    return min(tied, key=lambda i: reps[i]), len(tied)

def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_gate_answer__", "rb")
    except PermissionError:
        guarded = True
    public = json.loads(sys.stdin.read())
    if public.get("hypothesis") != HYPOTHESIS:
        raise ValueError("wrong hypothesis")
    public["hypothesis"] = "H031-pgl-full-v2"
    model, jobs = validate_public(public)
    if any(len(j["pages"]) != 3 for j in jobs):
        raise ValueError("each gate job needs exactly 2 discovery and 1 holdout pages")
    if any(not math.isfinite(v) for v in model["start_weights"] + sum(model["transition_weights"], [])):
        raise ValueError("nonfinite model")
    reps = matrices()
    tables = np.asarray([mapping(m) for m in reps], dtype=np.int16)
    weights = np.asarray(model["transition_weights"])
    pair = weights[tables[:, :, None], tables[:, None, :]].reshape(len(reps), 900)
    starts = np.asarray(model["start_weights"])[tables]
    columns = []
    for job in jobs:
        cols = []
        for page in job["pages"]:
            c = page["counts"]
            if sum(c["starts"]) + sum(map(sum, c["transitions"])) != c["points"]:
                raise ValueError("counts do not conserve points")
            cols.append(np.r_[np.asarray(c["transitions"]).ravel(), c["starts"]] / c["points"])
        columns.append((cols[0] + cols[1]) / 2)
    all_scores = np.c_[pair, starts] @ np.asarray(columns).T
    results = []
    for j, job in enumerate(jobs):
        index, ties = select(all_scores[:, j], reps)
        h = job["pages"][2]["counts"]
        hs = float((pair[index] @ np.asarray(h["transitions"]).ravel() + starts[index] @ h["starts"]) / h["points"])
        results.append(dict(id=job["id"], matrix=list(reps[index]), mapping=tables[index].tolist(),
                            discovery_score=float(all_scores[index,j]), holdout_score=hs,ties=ties))
    print(json.dumps(dict(status="completed",read_guard_probe_passed=guarded,matrix_count=len(reps),results=results)))

if __name__ == "__main__":
    main()
