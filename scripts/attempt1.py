"""Execute the preregistered H006 batch; never retune from candidate outputs."""
from pathlib import Path
import argparse
import datetime as dt
import json
import math
import platform
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.execution import execute
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES, display
from lp_lab.synthetic import encode_text, independent_primes
from lp_lab.attempt1_stats import analyze

SPEC = "hypotheses/H006-prime-clock-extension-v1.json"
CORPUS = "data/attempt1-corpus-v1.json"
METHODS = ("page", "line", "paragraph", "corpus")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def public_page(page):
    cipher, line, paragraph = [], {0}, {0}
    for char in page["raw"]:
        if char in RUNES:
            cipher.append(RUNES.index(char))
        elif char == "/":
            line.add(len(cipher))
        elif char == "&":
            paragraph.add(len(cipher))
    return dict(page=page["page"], cipher=cipher,
                line_starts=sorted(i for i in line if i < len(cipher)),
                paragraph_starts=sorted(i for i in paragraph if i < len(cipher)))


def public_input(pages, counts):
    return dict(schema=1, hypothesis="H006-v1", training_counts=counts, pages=pages)


def invoke(public, folder, timeout=30):
    folder.mkdir(parents=True, exist_ok=False)
    write(folder / "public.json", public)
    execution = execute([sys.executable, "-I", "-S", str(ROOT / "scripts/attempt1_worker.py")],
                        cwd=ROOT, timeout=timeout, stdin=json.dumps(public))
    write(folder / "execution.json", execution)
    (folder / "stdout.json").write_text(execution["stdout"], encoding="utf8")
    (folder / "stderr.txt").write_text(execution["stderr"], encoding="utf8")
    if execution["status"] == "timeout":
        raise TimeoutError(f"worker timeout: {folder}")
    if execution["status"] != "completed":
        raise RuntimeError(f"worker error: {folder}; {execution['stderr']}")
    answer = json.loads(execution["stdout"])
    if not answer["read_guard_probe_passed"]:
        raise ValueError("Worker read isolation probe failed")
    return answer, execution


def verifier_delta(page, method, primes, offset):
    """Different clock construction: slice reset intervals rather than a live clock."""
    n = len(page["cipher"])
    if method == "corpus":
        prime_values = primes[offset:offset+n]
    else:
        boundaries = page.get(method + "_starts", [0]) + [n]
        prime_values = []
        for left, right in zip(boundaries, boundaries[1:]):
            prime_values.extend(primes[:right-left])
    return [(p-1) % 29 for p in prime_values]


def verify_worker(pages, output, weights):
    primes = independent_primes(sum(len(p["cipher"]) for p in pages))
    rows, offset, comparisons = output["results"], 0, []
    if output["raw_branch_evaluations"] != 4*len(pages) or output["unique_evaluations"] != len(rows):
        raise ValueError("Incorrect branch coverage counts")
    if {r["page"] for r in rows} != {p["page"] for p in pages}:
        raise ValueError("Worker omitted or added a page")
    for page in pages:
        page_rows = [r for r in rows if r["page"] == page["page"]]
        if sorted(m for row in page_rows for m in row["methods"]) != sorted(METHODS):
            raise ValueError("Branch omissions or duplicates")
        if len({tuple(r["delta"]) for r in page_rows}) != len(page_rows):
            raise ValueError("Correlated transforms were not deduplicated")
        for row in page_rows:
            for method in row["methods"]:
                expected_delta = verifier_delta(page, method, primes, offset)
                if row["delta"] != expected_delta:
                    raise ValueError("Independent clock verification failed")
            expected = [(c-d) % 29 for c, d in zip(page["cipher"], row["delta"])]
            if expected != row["plaintext"]:
                raise ValueError("Per-rune arithmetic verification failed")
            back = [(p+d) % 29 for p, d in zip(row["plaintext"], row["delta"])]
            if back != page["cipher"]:
                raise ValueError("Roundtrip failed")
            if not math.isclose(math.fsum(weights[p] for p in expected), row["log_likelihood"], abs_tol=1e-8):
                raise ValueError("Independent scorer calculation failed")
            comparisons.append(dict(page=page["page"], methods=row["methods"],
                                    rune_count=len(expected), delta_exact=True, arithmetic_exact=True,
                                    roundtrip_exact=True, plaintext_truth="unknown unless synthetic verifier"))
        offset += len(page["cipher"])
    return dict(status="passed", unique_transform_checks=len(comparisons), comparisons=comparisons)


def sensitivity(run, counts, weights):
    """Private deterministic heldout answers, never supplied to candidate worker."""
    heldout = encode_text((ROOT / "data/synthetic/heldout.txt").read_text(encoding="utf8"))
    primes = independent_primes(512)
    records = []
    for family in METHODS:
        pages, answers = [], []
        for number in range(2):
            plain = heldout[number*256:(number+1)*256]
            if len(plain) != 256:
                raise ValueError("Heldout text too short")
            page = dict(page=f"synthetic/{family}/{number}", cipher=[0]*256,
                        line_starts=list(range(0,256,32)), paragraph_starts=[0,128])
            delta = verifier_delta(page, family, primes, number*256)
            page["cipher"] = [(p+d) % 29 for p, d in zip(plain, delta)]
            pages.append(page)
            answers.append(dict(page=page["page"], method=family, plaintext=plain, delta=delta))
        folder = run / "sensitivity" / family
        output, execution = invoke(public_input(pages, counts), folder)
        write(folder / "verifier-only/answers.json", answers)
        checks = verify_worker(pages, output, weights)
        rows = []
        for answer in answers:
            for row in (r for r in output["results"] if r["page"] == answer["page"]):
                mismatch = [i for i,(p,q) in enumerate(zip(answer["plaintext"],row["plaintext"])) if p != q]
                true_branch = family in row["methods"]
                if true_branch and mismatch:
                    raise ValueError("Synthetic true branch failed exact recovery")
                if not true_branch and not mismatch:
                    raise ValueError("Undeduplicated synthetic equivalent branch")
                rows.append(dict(page=row["page"], methods=row["methods"], matching_family=true_branch,
                                 mismatch_count=len(mismatch), status="passed" if true_branch else "negative"))
        write(folder / "verification.json", dict(arithmetic=checks, exact_recovery=rows))
        records.extend(rows)
    result = dict(status="passed", cases=8, branch_evaluations=32, rows=records,
                  limitation="Two fixed heldout 256-rune slices reused across clocks. Exact algorithm sensitivity only, not a statistical power estimate or independent natural-language corpus.")
    write(run / "sensitivity/summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    started = dt.datetime.now(dt.timezone.utc)
    run = args.out or ROOT / "runs" / (started.strftime("%Y%m%dT%H%M%S.%fZ") + "-attempt1")
    run = run.resolve()
    if not run.is_relative_to((ROOT/"runs").resolve()):
        raise ValueError("Run folder must be inside repository runs")
    run.mkdir(parents=True, exist_ok=False)
    clock = time.monotonic()
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis="H006-v1", attempt="attempt 1", status="running",
                  started_at_utc=started.isoformat(), python=sys.version, executable=sys.executable,
                  platform=platform.platform(), code_version=snapshot, candidate_dispatch_started=False)
    write(run / "record.json", record)
    try:
        record["sources_verified"] = verify_sources(ROOT)
        spec = json.loads((ROOT/SPEC).read_text(encoding="utf8"))
        corpus = json.loads((ROOT/CORPUS).read_text(encoding="utf8"))
        all_pages = corpus["pages"]
        if [p["page"] for p in all_pages] != [f"LP2/{i}" for i in range(56)]:
            raise ValueError("Incomplete or misordered LP2 page universe")
        train = encode_text((ROOT/"data/synthetic/training.txt").read_text(encoding="utf8"))
        counts = [train.count(i) for i in range(29)]
        weights = [math.log((c+1)/(len(train)+29)) for c in counts]
        pages = [public_page(p) for p in all_pages if any(c in RUNES for c in p["raw"])]
        if len(pages) != 55 or [p["page"] for p in all_pages if not any(c in RUNES for c in p["raw"])] != ["LP2/50"]:
            raise ValueError("Applicability scope changed; new experiment version required")
        frozen_paths = [SPEC, CORPUS, "data/synthetic/training.txt", "data/synthetic/heldout.txt",
                        "data/pages/lp2_56.json", "data/pages/lp2_57.json"]
        frozen_paths += [p.relative_to(ROOT).as_posix() for p in (ROOT/"sources").glob("*manifest.json")]
        freeze = dict(frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), specification=spec,
                      hashes={p:sha256(ROOT/p) for p in frozen_paths}, code_version=snapshot,
                      counts=counts, weights=weights, public=public_input(pages, counts))
        write(run / "frozen.json", freeze)
        record["frozen_sha256"] = sha256(run/"frozen.json")
        record["sensitivity"] = sensitivity(run, counts, weights)
        baseline = execute([sys.executable,"-X","utf8","scripts/reproduce.py","--out",str(run/"known")],cwd=ROOT,timeout=30)
        write(run/"known-execution.json", baseline)
        (run/"known.stdout.txt").write_text(baseline["stdout"],encoding="utf8")
        (run/"known.stderr.txt").write_text(baseline["stderr"],encoding="utf8")
        if baseline["status"] != "completed":
            raise RuntimeError("Known baseline failed before unsolved dispatch")
        record["candidate_dispatch_started"] = True
        record["candidate_dispatch_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write(run/"record.json",record)
        output, execution = invoke(freeze["public"],run/"discovery")
        record["discovery_execution"] = {k:v for k,v in execution.items() if k not in {"stdout","stderr"}}
        record["actual_coverage"] = dict(universe_pages=56, applicable_pages=55, excluded_pages=["LP2/50"],
                                         rune_count=output["rune_count"], raw_branches=output["raw_branch_evaluations"],
                                         unique_transforms=output["unique_evaluations"])
        write(run/"record.json",record)
        verification = verify_worker(pages, output, weights)
        write(run/"independent-verification.json", verification)
        remaining = spec["total_budget"]["wall_seconds"] - (time.monotonic()-clock)
        if remaining <= 0:
            raise TimeoutError("Batch wall budget exhausted before permutation controls")
        stats = analyze(pages, output["results"], weights, run/"statistics", timeout_seconds=min(180,remaining))
        write(run/"statistics/summary.json",stats)
        coverage = []
        for page in all_pages:
            candidates = [r for r in output["results"] if r["page"] == page["page"]]
            stat_rows = [r for r in stats["rows"] if r["page"] == page["page"]]
            paths = []
            for row in candidates:
                ident = f"{page['page'].replace('/','_')}-{'-'.join(row['methods'])}"
                values = iter(row["plaintext"])
                raw = "".join(RUNES[next(values)] if c in RUNES else c for c in page["raw"])
                values = iter(row["plaintext"])
                latin = "".join(display(next(values)) if c in RUNES else c for c in page["raw"])
                raw_path = run/"candidates"/(ident+".txt")
                raw_path.parent.mkdir(parents=True,exist_ok=True)
                raw_path.write_text(raw,encoding="utf8",newline="")
                (run/"candidates"/(ident+"-latin.txt")).write_text(latin,encoding="utf8",newline="")
                paths.append(raw_path.relative_to(ROOT).as_posix())
            coverage.append(dict(page_or_section=page["page"], applicability=bool(candidates),
                                 inapplicability_reason=None if candidates else "Literal grid only; zero rune tokens; unexecuted, not negative",
                                 method_id="H006-v1", actual_parameter_coverage=stat_rows,
                                 uncovered_parameters=spec["uncovered_parameters"],
                                 result_status=("inconclusive" if any(r["status"]=="inconclusive" for r in stat_rows) else "negative") if candidates else "inconclusive",
                                 candidate_evidence=paths, elapsed_seconds=execution["elapsed_seconds"],
                                 elapsed_scope="shared worker batch, not an independently measured per-page time",
                                 exit_code=execution["exit_code"] if candidates else None,
                                 stdout_path=(run/"discovery/stdout.json").relative_to(ROOT).as_posix(),
                                 stderr_path=(run/"discovery/stderr.txt").relative_to(ROOT).as_posix(),
                                 incomplete_reason=None if candidates else "not applicable to rune-domain hypothesis"))
        write(run/"coverage.json",dict(schema=1,rows=coverage))
        record["result"] = dict(status="inconclusive" if stats["lead_count"] else "negative", lead_count=stats["lead_count"],
                              completed_control_replicates=stats["completed_control_replicates"],
                              meaning="Frequency-alignment leads only; no decipherment accepted.")
        record["status"] = record["result"]["status"]
        record["deciphered_pages"] = []
        record["verification_status"] = verification["status"]
        if code_snapshot(ROOT) != snapshot or any(sha256(ROOT/p)!=h for p,h in freeze["hashes"].items()):
            raise ValueError("Frozen code or inputs changed during execution")
        verify_sources(ROOT)
        if time.monotonic()-clock > spec["total_budget"]["wall_seconds"]:
            raise TimeoutError("Batch wall budget exceeded")
    except Exception as exc:
        record["status"] = "timeout" if isinstance(exc,TimeoutError) else "error"
        record["error"] = repr(exc)
        (run/"exception.stderr.txt").write_text(traceback.format_exc(),encoding="utf8")
    record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    record["elapsed_seconds"] = time.monotonic()-clock
    write(run/"record.json",record)
    # Portable evidence: source bytes, code, preregistration, raw logs and candidates.
    archive = run/"attempt1-bundle.zip"
    files = [ROOT/p for p in snapshot["files"]]
    for directory in ("sources", "data", "hypotheses", "research"):
        files += [p for p in (ROOT/directory).rglob("*") if p.is_file()]
    knowledge = json.loads((ROOT/"research/knowledge.json").read_text(encoding="utf8"))
    files += [ROOT/e["artifact"] for e in knowledge["experiments"]]
    files += [ROOT/name for name in ("README.md","AGENTS.md","STATE.md")]
    files += [p for p in run.rglob("*") if p.is_file()]
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(set(files)):
            bundle.write(p,p.relative_to(ROOT).as_posix())
    write(run/"bundle-integrity.json",dict(path=archive.name,sha256=sha256(archive),bytes=archive.stat().st_size,
                                         note="Sidecar not inside bundle; record.json is the immutable completed experiment record."))
    print(json.dumps(dict(run=run.relative_to(ROOT).as_posix(),status=record["status"],coverage=record.get("actual_coverage"),result=record.get("result"),error=record.get("error"))))
    return 0 if record["status"] in {"negative","inconclusive","passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
