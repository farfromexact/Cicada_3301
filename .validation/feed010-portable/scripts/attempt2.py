"""H001/H002 exact known-page discrimination; append-only, bounded, offline run."""
from pathlib import Path
import argparse
from collections import Counter
import datetime as dt
import hashlib
import itertools
import json
import re
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.boundary_clock import BRANCHES, HASH_SPANS
from lp_lab.execution import execute
from lp_lab.model import tokenize
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.reference import reference_indices
from lp_lab.runes import RUNES, indices, display
from lp_lab.synthetic import independent_primes

MASTER = "sources/iddqd/liber-primus__transcription--master/liber-primus__transcription--master.txt"
REFERENCES = {"LP1/03": "sources/clues-v1/ibot/liber_primus/markdown/03.md",
              "LP1/04": "sources/attempt2/ibot/liber_primus/markdown/04.md",
              "LP2/56": "sources/ibot/liber_primus/markdown/73.md"}
SPECS = ["hypotheses/H001-skip-clock-v1.json", "hypotheses/H002-boundary-clock-v1.json"]
KEY = [23, 10, 1, 10, 9, 10, 16, 26]
POLICIES = ("none", "specified_free", "specified_consume", "all_cipher_f_free")
LP1_SKIP = [48,74,84,132,159,160,250,421,443,465,514]
DELIMITERS = "-.,/&$§%;"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf8")


def raw_digest(raw):
    return hashlib.sha256(raw.encode("utf8")).hexdigest()


def prepare_inputs():
    master = (ROOT/MASTER).read_bytes().decode("utf8")
    sections = master.split("%")
    pages = []
    for page, segment in (("LP1/03",2),("LP1/04",3)):
        md = (ROOT/REFERENCES[page]).read_text(encoding="utf8")
        blocks = re.findall(r"```\n(.*?)```",md,re.S)
        raw = sections[segment]
        if indices(raw) != indices(blocks[0]) or indices(raw) != indices(blocks[1]):
            raise ValueError("Cross-source cipher sequence mismatch")
        image_path = "sources/attempt2/iddqd/"+page.replace("/","-")+".jpg"
        pages.append(dict(page=page,raw=raw,source=MASTER,source_sha256=sha256(ROOT/MASTER),
                          extraction=dict(percent_split_index=segment,newlines="original CRLF retained"),
                          raw_sha256=raw_digest(raw),image_path=image_path,image_sha256=sha256(ROOT/image_path),
                          tokens=tokenize(raw,page,image_path,{}),rune_count=len(indices(raw))))
    known = json.loads((ROOT/"data/pages/lp2_56.json").read_text(encoding="utf8"))
    pages.append(dict(page="LP2/56",raw=known["raw"],source="data/pages/lp2_56.json",
                      source_sha256=sha256(ROOT/"data/pages/lp2_56.json"),
                      extraction=dict(method="existing versioned raw",newlines="legacy LF derived from pinned master"),
                      raw_sha256=raw_digest(known["raw"]),image_path=known["image_path"],tokens=known["tokens"],rune_count=85))
    if [p["rune_count"] for p in pages] != [251,264,85]:
        raise ValueError("Known page universe changed")
    md4 = (ROOT/REFERENCES["LP1/04"]).read_text(encoding="utf8")
    single = re.search(r"Enter a sentence to translate:\n > ([^\n]+)",md4).group(1)
    offsets = [59,95,108,170,204,205,312,523,551,578,638]
    if indices(single) != indices(pages[0]["raw"]+pages[1]["raw"]):
        raise ValueError("Combined source string disagrees")
    mapped = []
    for offset in offsets:
        if single[offset-1] != RUNES[0]:
            raise ValueError("One-based source skip is not F")
        mapped.append(len(indices(single[:offset-1])))
    if mapped != LP1_SKIP:
        raise ValueError("Source coordinate mapping changed")
    md56 = (ROOT/REFERENCES["LP2/56"]).read_text(encoding="utf8")
    flat56 = re.findall(r"```\n(.*?)```",md56,re.S)[1].strip()
    if flat56[202] != RUNES[0] or len(indices(flat56[:202])) != 56:
        raise ValueError("LP2 zero-based skip mapping changed")
    answers = {p["page"]:dict(indices=reference_indices(ROOT/REFERENCES[p["page"]]),
                                  source=REFERENCES[p["page"]],source_sha256=sha256(ROOT/REFERENCES[p["page"]])) for p in pages}
    if any(len(answers[p["page"]]["indices"]) != p["rune_count"] for p in pages):
        raise ValueError("Independent expected length mismatch")
    return pages, answers, dict(lp1=dict(source_codepoint_base=1,offsets=offsets,global_rune_ordinals=mapped),
                               lp2_56=dict(source_codepoint_base=0,offsets=[202],global_rune_ordinals=[56]))


def make_jobs(pages):
    lp1 = [{"page":p["page"],"raw":p["raw"]} for p in pages[:2]]
    lp56 = [{"page":pages[2]["page"],"raw":pages[2]["raw"]}]
    jobs = []
    for direction, policy, continuity in itertools.product(("subtract","add"),POLICIES,("continuous","page_reset")):
        jobs.append(dict(id=f"H001-divinity-{direction}-{policy}-{continuity}",kind="skip",pages=lp1,
                         parameters=dict(mode="vigenere",direction=direction,policy=policy,continuity=continuity,specified_skip=LP1_SKIP,key=KEY)))
    for policy in POLICIES:
        jobs.append(dict(id=f"H001-prime-{policy}",kind="skip",pages=lp56,
                         parameters=dict(mode="prime",direction="subtract",policy=policy,continuity="continuous",specified_skip=[56],key=KEY)))
    for branch in BRANCHES:
        jobs.append(dict(id=f"H002-{branch}",kind="boundary",pages=lp56,
                         parameters=dict(branch=branch,skip_ordinal=56,title_boundary=8,hash_spans=HASH_SPANS)))
    if len(jobs) != 26:
        raise ValueError("Registered 26-case budget changed")
    return jobs


def independent_targets(job):
    """Prefix sums and reset intervals; separate from either worker engine."""
    params = job["parameters"]
    ps = independent_primes(1200)
    targets, deltas, clocks = {}, {}, {}
    if job["kind"] == "skip":
        originals = [v for p in job["pages"] for v in indices(p["raw"])]
        policy = params["policy"]
        skip = set() if policy == "none" else ({i for i,c in enumerate(originals) if c == 0} if policy == "all_cipher_f_free" else set(params["specified_skip"]))
        consumes = [int(policy == "specified_consume" or i not in skip) for i in range(len(originals))]
        prefix = [0]+list(itertools.accumulate(consumes))
        offset = 0
        sign = -1 if params["direction"] == "subtract" else 1
        for page in job["pages"]:
            cs = indices(page["raw"])
            base = prefix[offset] if params["continuity"] == "page_reset" else 0
            ts = [prefix[offset+i]-base for i in range(len(cs))]
            ds = [0 if offset+i in skip else ((ps[t]-1)%29 if params["mode"]=="prime" else params["key"][t%len(params["key"])] ) for i,t in enumerate(ts)]
            targets[page["page"]] = [(c+sign*d)%29 for c,d in zip(cs,ds)]
            deltas[page["page"]] = [sign*d for d in ds]
            clocks[page["page"]] = ts
            offset += len(cs)
        final_clock = prefix[-1] - (prefix[offset-len(cs)] if params["continuity"] == "page_reset" else 0)
    else:
        page = job["pages"][0]
        raw, branch = page["raw"],params["branch"]
        rune_offsets = [i for i,c in enumerate(raw) if c in RUNES]
        skipped_offset = rune_offsets[params["skip_ordinal"]]
        consumed = [int((c in RUNES and i != skipped_offset) or
                        (branch=="hash_advance" and any(a<=i<b for a,b in params["hash_spans"])) or
                        (branch=="delimiter_advance" and c in DELIMITERS)) for i,c in enumerate(raw)]
        prefix = [0]+list(itertools.accumulate(consumed))
        reset = [0]
        if branch in {"line_reset","paragraph_reset"}:
            marker = "/" if branch == "line_reset" else "&"
            reset += [i+1 for i,c in enumerate(raw) if c == marker]
        if branch == "title_reset":
            reset.append(params["title_boundary"])
        ts = [prefix[i]-prefix[max(s for s in reset if s<=i)] for i in rune_offsets]
        ds = [0 if i == params["skip_ordinal"] else (ps[t]-1)%29 for i,t in enumerate(ts)]
        targets[page["page"]] = [(c-d)%29 for c,d in zip(indices(raw),ds)]
        deltas[page["page"]] = [-d for d in ds]
        clocks[page["page"]] = ts
        final_clock = prefix[-1]-prefix[max(reset)]
    return targets,deltas,clocks,final_clock


def validate_case(job, result, answers, run):
    targets,deltas,clocks,final_clock = independent_targets(job)
    if result["final_clock"] != final_clock:
        raise ValueError("Independent final clock mismatch")
    if [p["page"] for p in result["pages"]] != [p["page"] for p in job["pages"]]:
        raise ValueError("Worker altered page order")
    page_rows = []
    for original, actual in zip(job["pages"],result["pages"]):
        page = original["page"]
        decoded = indices(actual["raw"])
        trace_steps = [s for s in result["steps"] if s["page"]==page] if job["kind"]=="skip" else result["steps"]
        trace_clocks = [s["clock_index"] if job["kind"]=="skip" else s["clock_before"] for s in trace_steps]
        if trace_clocks != clocks[page]:
            raise ValueError("Independent per-rune clock trace mismatch")
        if decoded != actual["indices"] or decoded != targets[page]:
            raise ValueError("Independent every-rune arithmetic check failed")
        if len(actual["raw"]) != len(original["raw"]) or any(a!=b for a,b in zip(original["raw"],actual["raw"]) if a not in RUNES):
            raise ValueError("Non-rune formatting changed")
        reencrypted = [(p-d)%29 for p,d in zip(decoded,deltas[page])]
        if reencrypted != indices(original["raw"]):
            raise ValueError("Frozen-path inverse mismatch")
        expected = answers[page]["indices"]
        differences = [i for i,(a,b) in enumerate(zip(decoded,expected)) if a!=b]
        rune_offsets = [i for i,c in enumerate(original["raw"]) if c in RUNES]
        trace = [dict(rune_ordinal=i,source_offset=rune_offsets[i],expected=e,actual=a,equal=e==a,independent_clock=clocks[page][i],signed_delta=deltas[page][i]) for i,(e,a) in enumerate(zip(expected,decoded))]
        stem = job["id"]+"-"+page.replace("/","_")
        dest = run/"comparisons"/(stem+".json")
        write(dest,dict(page=page,steps=trace,roundtrip_exact=True,non_runes_exact=True,arithmetic_exact=True))
        (dest.parent/(stem+".txt")).write_text(actual["raw"],encoding="utf8",newline="")
        values = iter(decoded)
        latin = "".join(display(next(values)) if c in RUNES else c for c in actual["raw"])
        (dest.parent/(stem+"-latin.txt")).write_text(latin,encoding="utf8",newline="")
        page_rows.append(dict(page=page,status="negative" if differences else "passed",rune_count=len(decoded),
                              mismatch_count=len(differences),first_mismatch=differences[0] if differences else None,
                              first_mismatch_source_offset=rune_offsets[differences[0]] if differences else None,
                              mismatch_ordinals=differences,comparison_path=dest.relative_to(ROOT).as_posix(),roundtrip_exact=True))
    return dict(id=job["id"],kind=job["kind"],parameters=job["parameters"],status="passed" if all(r["status"]=="passed" for r in page_rows) else "negative",pages=page_rows,
                mismatch_count=sum(r["mismatch_count"] for r in page_rows),final_clock=result["final_clock"],
                known_plaintext_only=True)


def plaintext_f_diagnostic(job, answers):
    plain = [c for page in job["pages"] for c in answers[page["page"]]["indices"]]
    cipher = [c for page in job["pages"] for c in indices(page["raw"])]
    skips = [i for i,p in enumerate(plain) if p==0]
    ps = independent_primes(len(plain))
    forward,clock = [],0
    for p in plain:
        if p == 0:
            forward.append(0)
        else:
            delta = ps[clock]-1 if job["parameters"]["mode"] == "prime" else KEY[clock%len(KEY)]
            forward.append((p+delta)%29)
            clock += 1
    return dict(source_skip=job["parameters"]["specified_skip"],expected_plaintext_f=skips,
                same_mask=skips==job["parameters"]["specified_skip"],forward_from_plaintext_f_exact=forward==cipher,
                cipher_f=[i for i,c in enumerate(cipher) if c==0],
                ordinary_cipher_f=[i for i,(p,c) in enumerate(zip(plain,cipher)) if c==0 and p!=0],
                non_f_consumed=clock,interpretation="Scoped observed compatibility on exact known pages; not a universal skip selector from ciphertext")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT/"runs").resolve()):
        raise ValueError("Run must be within repository runs")
    run.mkdir(parents=True,exist_ok=False)
    start = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1,attempt="attempt 2",hypotheses=["H001-v1","H002-v1"],status="running",
                  started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),code_version=snapshot,
                  unsolved_page_candidates=0,execution_started=False)
    write(run/"record.json",record)
    try:
        record["sources_verified"] = verify_sources(ROOT)
        for spec_path in SPECS:
            specification = json.loads((ROOT/spec_path).read_text(encoding="utf8"))
            for entry in specification.get("sources",specification.get("inputs",[])):
                if sha256(ROOT/entry["path"]) != entry["sha256"]:
                    raise ValueError("Preregistered source hash mismatch")
        pages,answers,coordinates = prepare_inputs()
        boundary_spec = json.loads((ROOT/SPECS[1]).read_text(encoding="utf8"))
        if pages[2]["raw_sha256"] != boundary_spec["raw_sha256"]:
            raise ValueError("Preregistered LP2/56 raw version mismatch")
        jobs = make_jobs(pages)
        write(run/"inputs.json",dict(schema=1,derived_at_utc=record["started_at_utc"],version="attempt2-known-v1",pages=pages,coordinates=coordinates))
        write(run/"verifier-only/answers.json",answers)
        public = dict(schema=1,experiment="attempt2-mechanics-v1",jobs=jobs)
        write(run/"public.json",public)
        paths = SPECS+[MASTER,*REFERENCES.values(),"data/pages/lp2_56.json"]
        paths += [p.relative_to(ROOT).as_posix() for p in (ROOT/"sources").glob("*manifest.json")]
        freeze = dict(frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),specifications=[json.loads((ROOT/p).read_text(encoding="utf8")) for p in SPECS],
                      source_hashes={p:sha256(ROOT/p) for p in paths},code_version=snapshot,
                      inputs_sha256=sha256(run/"inputs.json"),public_sha256=sha256(run/"public.json"),
                      expected_sha256=sha256(run/"verifier-only/answers.json"),configuration_count=len(jobs),maximum_worker_seconds=30)
        write(run/"frozen.json",freeze)
        record.update(execution_started=True,dispatched_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),frozen_sha256=sha256(run/"frozen.json"))
        write(run/"record.json",record)
        execution = execute([sys.executable,"-I","-S",str(ROOT/"scripts/attempt2_worker.py")],cwd=ROOT,timeout=30,stdin=json.dumps(public))
        write(run/"execution.json",execution)
        (run/"stdout.json").write_text(execution["stdout"],encoding="utf8")
        (run/"stderr.txt").write_text(execution["stderr"],encoding="utf8")
        if execution["status"] == "timeout":
            raise TimeoutError("Known-page worker timed out")
        if execution["status"] != "completed":
            raise RuntimeError("Known-page worker error; see execution.json and stderr.txt")
        output = json.loads(execution["stdout"])
        if not output["read_guard_probe_passed"] or [r["id"] for r in output["results"]] != [j["id"] for j in jobs]:
            raise ValueError("Worker guard or coverage mismatch")
        rows = [validate_case(j,o["result"],answers,run) for j,o in zip(jobs,output["results"])]
        primary = ["H001-divinity-subtract-specified_free-continuous","H001-prime-specified_free","H002-continuous"]
        aliases = {}
        for job,out in zip(jobs,output["results"]):
            _,ds,_,_ = independent_targets(job)
            identity = json.dumps([(p["page"],[d%29 for d in ds[p["page"]]]) for p in job["pages"]])
            aliases.setdefault(identity,[]).append(job["id"])
        diagnostics = {j["id"]:plaintext_f_diagnostic(j,answers) for j in jobs if j["id"] in primary[:2] and next(r for r in rows if r["id"]==j["id"])["status"]=="passed"}
        write(run/"plaintext-f-diagnostic.json",diagnostics)
        summary = dict(status="passed" if all(next(r for r in rows if r["id"]==p)["status"]=="passed" for p in primary) else "negative",
                       cases=len(rows),case_statuses=dict(Counter(r["status"] for r in rows)),known_pages=[p["page"] for p in pages],
                       known_runes=600,configuration_rune_comparisons=sum(p["rune_count"] for r in rows for p in r["pages"]),
                       primary_cases=primary,unique_effective_paths=len(aliases),equivalent_cases=[v for v in aliases.values() if len(v)>1],
                       unsolved_page_candidates=0,deciphered_new_pages=[],rows=rows,
                       inverse_limit="Uses frozen skip mask/clock path. Unknown-ciphertext skip recovery or unique invertibility is not established.")
        write(run/"summary.json",summary)
        excluded=[dict(page=f"LP2/{i}",applicability=False,status="inconclusive",executed=False,
                       reason="No independent exact expected plaintext; this is a known-page mechanism audit, not a universal unsolved hypothesis. LP2/50 also has no rune tokens.") for i in range(56)]
        write(run/"coverage.json",dict(actual=rows,unsolved_universe=excluded,other_known_pages="LP1 remaining pages and LP2/57 not applicable to these exact key/clock mechanisms"))
        if code_snapshot(ROOT)!=snapshot or any(sha256(ROOT/p)!=h for p,h in freeze["source_hashes"].items()):
            raise ValueError("Code/spec/input changed during experiment")
        verify_sources(ROOT)
        record.update(status=summary["status"],cases=summary["cases"],case_statuses=summary["case_statuses"],
                      unique_effective_paths=summary["unique_effective_paths"],known_runes=600,
                      configuration_rune_comparisons=summary["configuration_rune_comparisons"],all_arithmetic_and_inverse_checks="passed")
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc,TimeoutError) else "error",error=repr(exc))
        (run/"exception.stderr.txt").write_text(traceback.format_exc(),encoding="utf8")
    record.update(finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-start)
    write(run/"record.json",record)
    files=[ROOT/p for p in snapshot["files"]]
    for directory in ("sources","data","hypotheses","research"):
        files += [p for p in (ROOT/directory).rglob("*") if p.is_file()]
    knowledge=json.loads((ROOT/"research/knowledge.json").read_text(encoding="utf8"))
    files += [ROOT/e["artifact"] for e in knowledge["experiments"]]
    files += [ROOT/name for name in ("README.md","AGENTS.md","STATE.md")]
    files += [p for p in run.rglob("*") if p.is_file()]
    archive=run/"attempt2-bundle.zip"
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(set(files)):
            bundle.write(p,p.relative_to(ROOT).as_posix())
    write(run/"bundle-integrity.json",dict(path=archive.name,sha256=sha256(archive),members=len(set(files))))
    print(json.dumps({"run":run.relative_to(ROOT).as_posix(), **{k:record.get(k) for k in
                     ("status","cases","case_statuses","unique_effective_paths","known_runes","configuration_rune_comparisons","unsolved_page_candidates","elapsed_seconds","error")}},ensure_ascii=False))
    return 0 if record["status"] in {"passed","negative","inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
