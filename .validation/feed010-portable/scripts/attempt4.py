"""H008: bounded cipher-agnostic structure diagnostics, with immutable run output."""
from pathlib import Path
import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
import sys
import time
import traceback
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.provenance import sha256, verify_sources
from lp_lab.runes import RUNES
from lp_lab.structure_inputs import prepare_page
from lp_lab.structure_stats import randomized_scan

SPEC = "hypotheses/H008-structure-v1.json"
CORPUS = "data/attempt1-corpus-v1.json"
CODE = ["scripts/attempt4.py", "src/lp_lab/structure_inputs.py", "src/lp_lab/structure_stats.py",
        "src/lp_lab/provenance.py", "src/lp_lab/runes.py", "tests/test_structure_inputs.py",
        "tests/test_structure_stats.py"]


def plain(x):
    if isinstance(x, dict):
        return {k: plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [plain(v) for v in x]
    if isinstance(x, np.ndarray):
        return plain(x.tolist())
    if isinstance(x, np.generic):
        return plain(x.item())
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf8")


def location(page, start, length=1):
    ts = page["rune_tokens"][start:start+length]
    return dict(page=page["page"], ordinal=start, length=length,
                indices=page["indices"][start:start+length],
                glyphs="".join(RUNES[x] for x in page["indices"][start:start+length]),
                token_ids=[t["id"] for t in ts],
                source_offsets=[t["source_offset"] for t in ts],
                image_lines=[t["line"] for t in ts], tokens=ts)


def localize(pages, results):
    """Measurement drilldown only; no new statistical score or key generation."""
    a, b, c = [results["families"][k] for k in "ABC"]
    ai = int(np.argmax(a["observed_z"]))
    pi, li = divmod(ai, 29)
    p, lag = pages[pi], li+1
    pair_positions = [i for i in range(len(p["indices"])-lag)
                      if p["groups"][i] == p["groups"][i+lag] and p["indices"][i] == p["indices"][i+lag]]
    ap = dict(page=p["page"], lag=lag, count=len(pair_positions), column=ai,
              z=a["observed_z"][ai], p_adjusted=a["p_adjusted"][ai], formal_lead=a["lead"][ai],
              pairs=[dict(left=location(p,i),right=location(p,i+lag)) for i in pair_positions])
    bi = int(np.argmax(b["observed_z"]))
    p = pages[bi]
    counts = [[0, 0] for _ in range(29)]
    for i, rune in enumerate(p["indices"]):
        if p["boundary_eligible"][i]:
            counts[rune][p["hyphen_mask"][i]] += 1
    bp = dict(page=p["page"], column=bi, g=b["observed"][bi],
              z=b["observed_z"][bi], p_adjusted=b["p_adjusted"][bi], formal_lead=b["lead"][bi],
              counts_by_rune_nonhyphen_hyphen=counts,
              eligible=p["boundary_eligible"], hyphen_mask=p["hyphen_mask"],
              rune_locations=[location(p,i) for i in range(len(p["indices"]))])
    occurrences = defaultdict(list)
    for j, p in enumerate(pages):
        for start, end in p["segments"]:
            for i in range(start, end-3):
                occurrences[tuple(p["indices"][i:i+4])].append((j,i))
    motifs = []
    for key, locs in occurrences.items():
        perpage = Counter(j for j,i in locs)
        pairs = (len(locs)**2-sum(n*n for n in perpage.values()))//2
        if pairs:
            motifs.append((pairs,key,locs))
    motifs.sort(key=lambda x:(-x[0],x[1]))
    if sum(x[0] for x in motifs) != int(c["observed"]):
        raise ValueError("Independent C localization disagrees with statistics engine")
    cp = dict(count=c["observed"], p_adjusted=c["p_adjusted"], formal_lead=c["lead"],
              distinct_crosspage_motifs=len(motifs),
              motif_table=[dict(indices=list(k),glyphs="".join(RUNES[x] for x in k),crosspage_pairs=n,
                                occurrences=[dict(page=pages[j]["page"],ordinal=i) for j,i in locs]) for n,k,locs in motifs])
    if motifs:
        n,key,locs=motifs[0]
        extensions=[]
        for at, (j,i) in enumerate(locs):
            for k,h in locs[at+1:]:
                if j == k:
                    continue
                x,y=pages[j],pages[k]
                left=0
                while i-left-1 >= 0 and h-left-1 >= 0:
                    ii,hh=i-left-1,h-left-1
                    if x["groups"][ii] != x["groups"][i] or y["groups"][hh] != y["groups"][h] or x["indices"][ii] != y["indices"][hh]:
                        break
                    left+=1
                right=4
                while i+right < len(x["indices"]) and h+right < len(y["indices"]):
                    ii,hh=i+right,h+right
                    if x["groups"][ii] != x["groups"][i] or y["groups"][hh] != y["groups"][h] or x["indices"][ii] != y["indices"][hh]:
                        break
                    right+=1
                extensions.append(dict(left=location(x,i-left,left+right), right=location(y,h-left,left+right)))
        cp["selected_motif"]=dict(indices=list(key),crosspage_pairs=n,
                                  occurrences=[location(pages[j],i,4) for j,i in locs], extensions=extensions)
    return dict(A=ap,B=bp,C=cp,
                interpretation="Post-selection measurement localization; not an independent cryptanalytic validation or new family of tests")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="runs/attempt4-H008-v1")
    args=parser.parse_args()
    run=ROOT/args.out
    if not run.resolve().is_relative_to((ROOT/"runs").resolve()):
        raise ValueError("Output outside runs")
    run.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    report=dict(schema=1,hypothesis="H008-structure-v1",attempt=4,status="running",
                started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                environment=dict(python=sys.version,numpy=np.__version__,executable=sys.executable),
                command=sys.argv,code_version={p:sha256(ROOT/p) for p in CODE},
                spec_sha256=sha256(ROOT/SPEC),corpus_sha256=sha256(ROOT/CORPUS),
                new_keys_tested=0,new_plaintexts_claimed=0)
    write(run/"record.json",report)
    try:
        spec=json.loads((ROOT/SPEC).read_text(encoding="utf8"))
        if report["corpus_sha256"] != spec["data_versions"][0]["sha256"]:
            raise ValueError("Corpus hash mismatch")
        write(run/"frozen-spec.json",spec)
        report["source_files_verified"]=verify_sources(ROOT)
        corpus=json.loads((ROOT/CORPUS).read_text(encoding="utf8"))
        prepared=[prepare_page(p) for p in corpus["pages"]]
        pages=[p for p in prepared if p["indices"]]
        if len(prepared)!=56 or len(pages)!=55 or sum(len(p["indices"]) for p in pages)!=12956:
            raise ValueError("Unexpected page universe")
        write(run/"prepared-inputs.json",prepared)
        archive_paths={SPEC,CORPUS,*CODE,"sources/feed008/user-request.txt","sources/feed008-manifest.json"}
        for p in corpus["pages"]:
            archive_paths.add(p["source"] if isinstance(p["source"],str) else p["source"]["path"])
            archive_paths.add(p["image_path"])
        archive=run/"reproduction-bundle.zip"
        with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for path in sorted(archive_paths):
                z.write(ROOT/path,path)
        report["input_bundle_sha256"]=sha256(archive)
        report["input_bundle_members"]=len(archive_paths)
        report["scan_started_at_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
        write(run/"record.json",report)
        last=[0]
        def progress(info):
            if info["completed_control_replicates"]>=last[0]+100:
                last[0]=info["completed_control_replicates"]
                print("H008 controls",last[0],"elapsed",round(info["elapsed_seconds"],2),flush=True)
        result=randomized_scan(pages,permutations=999,seed=33010804,timeout_seconds=180,progress_callback=progress)
        arrays={}
        for family,values in result["families"].items():
            for key,value in values.items():
                if isinstance(value,np.ndarray):
                    arrays[family+"_"+key]=value
        np.savez_compressed(run/"null-statistics.npz",**arrays)
        compact={k:v for k,v in result.items() if k!="families"}
        compact["families"]={k:{j:v for j,v in x.items() if j not in {"null","null_z"}} for k,x in result["families"].items()}
        write(run/"statistics.json",compact)
        completed=result["status"]=="completed" and result["completed_control_replicates"]==999
        leads={k:bool(np.any(result["families"][k]["lead"])) for k in "ABC"}
        report.update(status=("passed" if any(leads.values()) else "negative") if completed else "timeout",
                      controls_completed=result["completed_control_replicates"],formal_lead_families=leads,
                      complete=completed,scan_elapsed_seconds=result["elapsed_seconds"],
                      coverage=dict(pages=55,runes=12956,A_columns=1595,B_columns=55,C_corpus_statistics=1),
                      unexecuted=spec["uncovered_parameters"])
        if completed:
            drill=localize(pages,result)
            write(run/"drilldown.json",drill)
            report["strongest"]={"A":{k:v for k,v in drill["A"].items() if k!="pairs"},
                                 "B":{k:v for k,v in drill["B"].items() if k not in {"rune_locations","eligible","hyphen_mask","counts_by_rune_nonhyphen_hyphen"}},
                                 "C":{k:v for k,v in drill["C"].items() if k not in {"motif_table","selected_motif"}}}
        coverage=[]
        for p in prepared:
            applicable=bool(p["indices"])
            j=pages.index(p) if applicable else None
            n=len(p["indices"])
            counts=np.bincount(p["indices"],minlength=29)
            families={}
            if applicable:
                for fam,ix in (("A",slice(j*29,(j+1)*29)),("B",j)):
                    f=result["families"][fam]
                    families[fam]=dict(observed=f["observed"][ix],p_adjusted=f["p_adjusted"][ix],lead=f["lead"][ix],discriminating=f["discriminating"][ix])
                families["C"]=dict(valid_windows=sum(max(0,e-s-3) for s,e in p["segments"]),
                                    result="Participation in joint corpus statistic; no per-page C p-value")
            coverage.append(dict(page_or_section=p["page"],applicability=applicable,
                inapplicability_reason=None if applicable else "No rune-domain symbols; grid remains literal",
                method_id="H008-structure-v1",actual_parameter_coverage=families,
                uncovered_parameters=spec["uncovered_parameters"],
                result_status=(report["status"] if not completed else ("passed" if any(bool(np.any(families[x]["lead"])) for x in ("A","B")) else "negative")) if applicable else "inconclusive",
                candidate_evidence="statistics.json and drilldown.json; C is corpus-level only" if applicable else None,
                elapsed_seconds=result["elapsed_seconds"],elapsed_scope="shared batch time, not per-page CPU",
                exit_code=0 if completed else 124,stdout_path="runner.stdout.txt",stderr_path="runner.stderr.txt",
                incomplete_reason=None if applicable and completed else ("No rune-domain symbols" if not applicable else "Control budget incomplete"),
                rune_count=n,segments=p["segments"],symbol_counts=counts,
                IC=float(sum(counts*(counts-1))/(n*(n-1))) if n>1 else None,
                source_metadata=p.get("metadata")))
        write(run/"coverage.json",coverage)
        if {p:sha256(ROOT/p) for p in CODE} != report["code_version"]:
            raise RuntimeError("H008 scoped code changed during execution")
        if sha256(ROOT/SPEC)!=report["spec_sha256"] or sha256(ROOT/CORPUS)!=report["corpus_sha256"]:
            raise RuntimeError("Frozen inputs changed during execution")
    except Exception as exc:
        report.update(status="error",error=repr(exc))
        traceback.print_exc()
    report["finished_at_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    report["elapsed_seconds"]=time.monotonic()-start
    write(run/"record.json",report)
    print(json.dumps(plain(report),ensure_ascii=True),flush=True)
    return 0 if report["status"] in {"passed","negative"} else 1


if __name__=="__main__":
    sys.exit(main())
