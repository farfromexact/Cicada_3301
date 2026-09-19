"""Verifier and orchestration for H031-v3; never reads LP2 corpus."""
from pathlib import Path
import argparse
import datetime as dt
import json
import math
import sys
import time
import traceback
import zipfile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attempt22_pgl_v2 as legacy
from lp_lab.provenance import sha256
from lp_lab.execution import execute
from lp_lab.r015_pgl_v2 import matrices, mapping, score_counts

HYPOTHESIS = "H031-pgl-power-gate-v3"
SPEC = ROOT / "hypotheses/H031-pgl-power-gate-v3.json"
WORKER = ROOT / "scripts/attempt22_pgl_gate_v3_worker.py"
write_json = legacy.write_json

def independent_gate(jobs, private, output, threshold, reps, tables, pair, starts, model):
    if len(output["results"]) != len(jobs) or {r["id"] for r in output["results"]} != {j["id"] for j in jobs}:
        raise ValueError("gate coverage mismatch")
    rows = {r["id"]:r for r in output["results"]}
    results = []
    for j, job in enumerate(jobs):
        scores = legacy.all_matrix_scores([p["counts"] for p in job["pages"][:2]],pair,starts)
        index, ds, ties = legacy.select_matrix(scores,reps)
        table = tuple(map(int,tables[index]))
        hs = legacy.score_scalar(table,job["pages"][2]["counts"],model)
        actual = rows[job["id"]]
        if actual["matrix"] != list(reps[index]) or actual["mapping"] != list(table):
            raise ValueError("independent map mismatch")
        if not all(math.isclose(actual[k],v,abs_tol=1e-10,rel_tol=1e-10) for k,v in [("discovery_score",ds),("holdout_score",hs)]):
            raise ValueError("independent score mismatch")
        if j == 0:
            scalar = [sum(legacy.score_scalar(tuple(map(int,t)),p["counts"],model) for p in job["pages"][:2])/2 for t in tables]
            if not np.allclose(scores,scalar,atol=1e-10,rtol=1e-10):
                raise ValueError("all-map scalar mismatch")
        expected = private[job["id"]]
        accepted = ds >= threshold and hs >= threshold
        exact = list(table) == expected.get("inverse") if expected["kind"] == "positive" else None
        rune_match = None
        if exact is not None:
            hp = expected["pages"][2]
            restored = [table[x] for x in hp["cipher"]]
            rune_match = sum(a == b for a,b in zip(restored,hp["plaintext"]))
            if exact and rune_match != hp["length"]:
                raise ValueError("heldout point recovery mismatch")
        results.append(dict(**actual,kind=expected["kind"],accepted=accepted,exact_mapping=exact,
                            heldout_exact_points=rune_match,positive_pass=bool(exact and accepted),independent=True))
    positive = sum(r["positive_pass"] for r in results)
    false = sum(r["accepted"] for r in results if r["kind"] != "positive")
    return dict(status="passed" if positive >= 18 and false == 0 else "failed",positive_passes=positive,
                positive_count=20,negative_false_accepts=false,negative_count=99,threshold=threshold,results=results)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to(ROOT / "runs"):
        raise ValueError("run outside runs")
    run.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    stamp = lambda: dt.datetime.now(dt.timezone.utc).isoformat()
    paths = [SPEC,WORKER,Path(__file__),ROOT/"scripts/attempt22_pgl_v2.py",ROOT/"scripts/attempt22_pgl_v2_worker.py",
             ROOT/"src/lp_lab/r015_pgl_v2.py",ROOT/"src/lp_lab/execution.py",ROOT/"src/lp_lab/provenance.py",
             ROOT/"src/lp_lab/runes.py",ROOT/"src/lp_lab/synthetic.py",ROOT/"src/lp_lab/cipher.py",ROOT/"src/lp_lab/__init__.py",
             ROOT/"data/synthetic/training.txt",ROOT/"data/synthetic/heldout.txt",ROOT/"hypotheses/H031-pgl-full-v2.json",
             ROOT/"research/feeds/FEED-011.json",ROOT/"reviews/feed011-composite-mechanisms.md"]
    hashes = {p.relative_to(ROOT).as_posix():sha256(p) for p in paths}
    record = dict(schema=1,hypothesis=HYPOTHESIS,status="running",started_at_utc=stamp(),unsolved_page_candidates=[],
                  actual_coverage=dict(synthetic_jobs=0,lp2_pages=0),source_hashes=hashes)
    write_json(run/"record.json",record)
    try:
        text = legacy.TRAIN_PATH.read_text(encoding="utf8")
        model = legacy.independent_model(legacy.training_segments(text))
        train = legacy.synthetic_flat_points(text)
        identity = tuple(range(30))
        calibration = [legacy.score_scalar(identity,legacy.independent_counts([train[s:s+n]]),model)
                       for n in [96,128,160,192,224] for s in range(0,len(train)-n+1,47)]
        threshold = min(calibration)-0.25
        write_json(run/"frozen.json",dict(hypothesis=HYPOTHESIS,frozen_at_utc=stamp(),threshold=threshold,
                    calibration_windows=len(calibration),calibration_source="training.txt only",source_hashes=hashes,
                    lp2_dispatch_allowed=False,model=model))
        reps = legacy.independent_matrices()
        tables,pair,starts = legacy.prepare_matrix_arrays(reps,model)
        other = matrices()
        if reps != other:
            raise ValueError("enumeration disagreement")
        for i,m in enumerate(other):
            actual = mapping(m)
            if actual != tuple(map(int,tables[i])):
                raise ValueError("independent mapping mismatch")
            inv = [0]*30
            for x,y in enumerate(actual): inv[y]=x
            if [inv[y] for y in actual] != list(range(30)):
                raise ValueError("inverse check failed")
        if len(set(map(tuple,tables.tolist()))) != 24360:
            raise ValueError("duplicate point bijections")
        write_json(run/"mapping-verification.json",dict(status="passed",matrices=24360,point_images=730800,inverses=24360,distinct_maps=24360))
        jobs,answers = legacy.make_gate(reps,model)
        answers.pop("threshold")
        write_json(run/"verifier-only/gate-answers.json",answers)
        public = dict(schema=1,hypothesis=HYPOTHESIS,model={k:model[k] for k in ["start_weights","transition_weights"]},jobs=jobs)
        write_json(run/"worker/public.json",public)
        execution = execute([sys.executable,"-I","-X","utf8",str(WORKER)],cwd=ROOT,timeout=600,stdin=json.dumps(public))
        write_json(run/"worker/execution.json",execution)
        (run/"worker/stdout.json").write_text(execution["stdout"],encoding="utf8")
        (run/"worker/stderr.txt").write_text(execution["stderr"],encoding="utf8")
        if execution["status"] != "completed":
            if execution["status"] == "timeout": raise TimeoutError("gate worker timeout")
            raise RuntimeError("gate worker failed")
        output = json.loads(execution["stdout"])
        if not output.get("read_guard_probe_passed"):
            raise ValueError("read guard absent")
        gate = independent_gate(jobs,answers["private"],output,threshold,reps,tables,pair,starts,model)
        write_json(run/"gate.json",gate)
        if time.monotonic()-started > 900: raise TimeoutError("gate wall budget")
        record.update(status="passed" if gate["status"]=="passed" else "inconclusive",gate_status=gate["status"],
                      positive_passes=gate["positive_passes"],negative_false_accepts=gate["negative_false_accepts"],
                      actual_coverage=dict(synthetic_jobs=119,matrices_per_job=24360,lp2_pages=0),
                      conclusion="Synthetic recovery gate only; no conclusion about LP2.")
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc,TimeoutError) else "error",error=repr(exc))
        (run/"runner.stderr.txt").write_text(traceback.format_exc(),encoding="utf8")
    if any(sha256(ROOT/p)!=h for p,h in hashes.items()):
        record.update(status="error",error="direct dependency changed during gate")
    record.update(finished_at_utc=stamp(),elapsed_seconds=time.monotonic()-started)
    write_json(run/"record.json",record)
    archive = run/"reproduction-bundle.zip"
    with zipfile.ZipFile(archive,"x",zipfile.ZIP_DEFLATED) as z:
        for p in paths + [p for p in run.rglob("*") if p.is_file() and p != archive]:
            z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError("archive CRC")
    write_json(run/"archive-manifest.json",dict(path=archive.relative_to(ROOT).as_posix(),sha256=sha256(archive),crc="passed"))
    print(json.dumps({k:v for k,v in record.items() if k != "source_hashes"},ensure_ascii=False))
    return 1 if record["status"] in {"error","timeout"} else 0

if __name__ == "__main__":
    sys.exit(main())
