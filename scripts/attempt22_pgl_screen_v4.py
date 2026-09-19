"""Verifier and orchestration for H031-v3; LP2 is opened only after the synthetic recovery gate passes."""
from pathlib import Path
import argparse
import datetime as dt
import json
import math
import random
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

HYPOTHESIS = "H031-pgl-gated-screen-v4"
SPEC = ROOT / "hypotheses/H031-pgl-gated-screen-v4.json"
WORKER = ROOT / "scripts/attempt22_pgl_screen_v4_worker.py"
write_json = legacy.write_json

def make_gate(reps,model):
    source = legacy.synthetic_flat_points(legacy.HELDOUT_PATH.read_text(encoding="utf8"))
    lengths = [96,128,160,192,224]
    rng = random.Random(33011532)
    jobs,private = [],{}
    for trial in range(119):
        positive = trial < 20
        i = trial if positive else trial-20
        slot = i % 20
        sizes = [lengths[(slot+j)%5] for j in range(3)]
        start = (slot*47+11) % (len(source)-sum(sizes)+1)
        kind = "positive" if positive else "uniform" if i < 33 else "within_permutation" if i < 66 else "global_s30"
        job_id = f"{'positive' if positive else 'negative'}-{i:02d}"
        permutation = list(range(30))
        if positive:
            permutation = list(legacy.independent_table(reps[(i*997+19)%len(reps)]))
        elif kind == "global_s30":
            rng.shuffle(permutation)
        pages,hidden = [],[]
        for j,n in enumerate(sizes):
            plain = source[start:start+n]
            cipher = [permutation[x] for x in plain]
            if kind == "uniform": cipher = [rng.randrange(30) for _ in plain]
            if kind == "within_permutation": rng.shuffle(cipher)
            page_id = f"{job_id}-p{j}"
            counts = legacy.independent_counts([cipher])
            pages.append(dict(page=page_id,counts=counts))
            hidden.append(dict(page=page_id,start=start,length=n,plaintext=plain,cipher=cipher,counts=counts))
            start += n
        if any(hidden[j]["start"]+hidden[j]["length"] > hidden[j+1]["start"] for j in [0,1]):
            raise ValueError("gate content overlaps within job")
        inverse = [0]*30
        for x,y in enumerate(permutation): inverse[y]=x
        private[job_id]=dict(kind=kind,pages=hidden,inverse=inverse if positive else None)
        jobs.append(dict(id=job_id,pages=pages))
    return jobs,dict(private=private)

def formal_screen(run,model,reps,tables,pair,starts,threshold,record):
    corpus = json.loads(legacy.CORPUS_PATH.read_text(encoding="utf8"))
    pages=[]
    coverage=[]
    for page in corpus["pages"]:
        segments,metadata=legacy.independent_segments(page["raw"])
        counts=legacy.independent_counts(segments)
        applicable=metadata["runes"]>0
        coverage.append(dict(page=page["page"],applicable=applicable,runes=metadata["runes"],
                             points=counts["points"],source_sha256=page["source_sha256"],raw_sha256=page["raw_sha256"],
                             reason=None if applicable else "No registered runes; alphanumeric grid excluded"))
        if applicable: pages.append(dict(page=page["page"],counts=counts,segments=segments))
    if len(pages)!=55 or sum(p["runes"] for p in coverage)!=12956:
        raise ValueError("formal coverage changed")
    discovery=[p for p in pages if p["page"] in legacy.DISCOVERY]
    holdout=[p for p in pages if p["page"] in legacy.HOLDOUT]
    # Worker receives discovery only. H is first scored after it selects a map.
    public=dict(schema=1,hypothesis=HYPOTHESIS,model={k:model[k] for k in ["start_weights","transition_weights"]},
                pages=[dict(page=p["page"],counts=p["counts"]) for p in discovery])
    write_json(run/"formal-worker/public.json",public)
    ex=execute([sys.executable,"-I","-X","utf8",str(WORKER)],cwd=ROOT,timeout=60,stdin=json.dumps(public))
    write_json(run/"formal-worker/execution.json",ex)
    (run/"formal-worker/stdout.json").write_text(ex["stdout"],encoding="utf8")
    (run/"formal-worker/stderr.txt").write_text(ex["stderr"],encoding="utf8")
    if ex["status"]!="completed": raise RuntimeError("formal worker failed")
    actual=json.loads(ex["stdout"])
    if not actual.get("read_guard_probe_passed"): raise ValueError("formal guard")
    actual=actual["results"][0]
    scores=legacy.all_matrix_scores([p["counts"] for p in discovery],pair,starts)
    index,ds,ties=legacy.select_matrix(scores,reps)
    table=tuple(map(int,tables[index]))
    if actual["matrix"]!=list(reps[index]) or not math.isclose(actual["discovery_score"],ds,abs_tol=1e-10):
        raise ValueError("formal independent selection mismatch")
    rows=[]
    inverse=[0]*30
    for x,y in enumerate(table): inverse[y]=x
    for p in pages:
        s=legacy.score_scalar(table,p["counts"],model)
        direct=score_counts(table,(p["counts"]["starts"],p["counts"]["transitions"],p["counts"]["points"]),model)
        if not math.isclose(s,direct,abs_tol=1e-10): raise ValueError("formal score check")
        decoded=[[table[x] for x in seg] for seg in p["segments"]]
        if [[inverse[y] for y in seg] for seg in decoded]!=p["segments"]: raise ValueError("formal round trip")
        rows.append(dict(page=p["page"],partition="discovery" if p["page"] in legacy.DISCOVERY else "holdout",
                         score=s,absolute_pass=s>=threshold,transformed_segments=decoded,
                         interpretation="Unverified transform, never a decrypted plaintext"))
    hpass=sum(r["absolute_pass"] for r in rows if r["partition"]=="holdout")
    necessary=ds>=threshold and hpass>=2
    screen=dict(status="inconclusive" if necessary else "negative",threshold=threshold,selected_matrix=list(reps[index]),
                discovery_mean=ds,discovery_pass=ds>=threshold,holdout_pages_above_threshold=hpass,
                necessary_condition_passed=necessary,controls_completed=0,statistical_significance="not tested",
                scope="Fixed common-map, literal-hyphen infinity, training-only scorer and absolute threshold screen only",
                rows=rows,leads=["common PGL map requires separate statistical confirmation"] if necessary else [])
    write_json(run/"screen.json",screen)
    write_json(run/"coverage.json",coverage)
    record.update(status=screen["status"],screen_summary={k:v for k,v in screen.items() if k!="rows"},
                  actual_coverage=dict(synthetic_jobs=119,matrices_per_job=24360,lp2_pages=55,lp2_runes=12956,
                                       discovery_pages=28,holdout_pages=27,formal_discovery_selections=1,controls=0),
                  conclusion="Frozen necessary score screen failed; stop this branch without randomization." if not necessary else "Screen lead only; confirmation not performed.")

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
             ROOT/"data/attempt1-corpus-v1.json",ROOT/"research/feeds/FEED-011.json",ROOT/"reviews/feed011-composite-mechanisms.md"]
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
                    lp2_dispatch_allowed="only after gate passes",model=model))
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
        jobs,answers = make_gate(reps,model)
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
        if time.monotonic()-started > 180: raise TimeoutError("gate wall budget")
        record.update(status="passed" if gate["status"]=="passed" else "inconclusive",gate_status=gate["status"],
                      positive_passes=gate["positive_passes"],negative_false_accepts=gate["negative_false_accepts"],
                      actual_coverage=dict(synthetic_jobs=119,matrices_per_job=24360,lp2_pages=0),
                      conclusion="Synthetic recovery gate only; no conclusion about LP2.")
        if gate["status"] == "passed":
            formal_screen(run,model,reps,tables,pair,starts,threshold,record)
        if time.monotonic()-started > 180: raise TimeoutError("screen wall budget")
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
