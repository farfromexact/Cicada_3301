"""Offline minimal closure; append-only run folder with commands and raw outputs."""
from pathlib import Path
import datetime as dt
import json
import platform
import subprocess
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.execution import execute

def main():
    started = dt.datetime.now(dt.timezone.utc)
    run = ROOT / "runs" / started.strftime("%Y%m%dT%H%M%S.%fZ")
    run.mkdir(parents=True, exist_ok=False)
    snapshot = code_snapshot(ROOT)
    # Archive actual code and input bytes, not just hashes of a moving worktree.
    archive = run / "reproduction-bundle.zip"
    bundle_paths = [ROOT / p for p in snapshot["files"]]
    for directory in ("data", "sources", "hypotheses", "research"):
        bundle_paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file())
    knowledge = json.loads((ROOT / "research/knowledge.json").read_text(encoding="utf8"))
    bundle_paths.extend(ROOT / e["artifact"] for e in knowledge["experiments"])
    bundle_paths.extend(ROOT / p for p in ("README.md", "AGENTS.md"))
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(set(bundle_paths)):
            bundle.write(p,p.relative_to(ROOT).as_posix())
    hypothesis = json.loads((ROOT / "hypotheses/H000-baseline.json").read_text(encoding="utf8"))
    git = subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True)
    report = dict(schema=1, hypothesis=hypothesis, started_at_utc=started.isoformat(),
                  additional_hypotheses=[json.loads((ROOT / p).read_text(encoding="utf8")) for p in
                      ("hypotheses/H004-clue-graph-v1.json","hypotheses/H005-math-representations-v1.json")],
                  environment=dict(python=sys.version, executable=sys.executable, platform=platform.platform()),
                  code_version=snapshot, git_head=git.stdout.strip() if git.returncode == 0 else None,
                  reproduction_bundle=dict(path=archive.name, sha256=sha256(archive)),
                  data_version={p.relative_to(ROOT).as_posix():sha256(p) for p in
                                [ROOT / "sources/manifest.json", ROOT / "sources/context-manifest.json", ROOT / "sources/clues-v1-manifest.json", ROOT / "sources/feed002-manifest.json", *sorted((ROOT / "research").rglob("*.json")), *sorted((ROOT / "data").rglob("*.json")),
                                 *sorted((ROOT / "data/synthetic").glob("*.txt"))]},
                  commands=[], status="running", next_step="See STATE.md; do not infer unsolved-page exclusion")
    def save():
        (run / "record.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    save()
    try:
        report["source_files_verified"] = verify_sources(ROOT)
        jobs = [("tests",[sys.executable,"-X","utf8","-m","unittest","discover","-s","tests","-v"],30),
                ("reproduce",[sys.executable,"-X","utf8","scripts/reproduce.py","--out",str(run / "reproduce")],30),
                ("research",[sys.executable,"-X","utf8","scripts/research.py","validate"],30),
                ("clues",[sys.executable,"-X","utf8","scripts/check_clues.py","--out",str(run / "clues")],30),
                ("math",[sys.executable,"-X","utf8","scripts/check_math.py","--out",str(run / "math")],30),
                ("synthetic",[sys.executable,"-X","utf8","scripts/synthetic_benchmark.py","--out",str(run / "synthetic")],60)]
        for name, command, timeout in jobs:
            result = execute(command,cwd=ROOT,timeout=timeout)
            report["commands"].append(dict(name=name,**result))
            (run / f"{name}.stdout.txt").write_text(result["stdout"],encoding="utf8")
            (run / f"{name}.stderr.txt").write_text(result["stderr"],encoding="utf8")
            print(name, result["status"], "exit", result["exit_code"])
            if result["stdout"]:
                print(result["stdout"].strip())
            save()
            if result["status"] != "completed":
                report["status"] = result["status"]
                break
        else:
            report["status"] = "passed"
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("Code changed during execution")
        if (run / "synthetic/summary.json").exists():
            summary = json.loads((run / "synthetic/summary.json").read_text(encoding="utf8"))
            report["status"] = summary["status"]
            report["actual_coverage"] = dict(known_pages=[56,57], known_runes=180,
                synthetic_trials=summary["trials"], unsolved_page_candidates=0)
            report["actual_coverage"]["additional_checks"] = json.loads((run / "clues/summary.json").read_text(encoding="utf8"))
            report["actual_coverage"]["math_checks"] = json.loads((run / "math/summary.json").read_text(encoding="utf8"))
            if report["actual_coverage"]["math_checks"]["status"] == "negative" and report["status"] == "passed":
                report["status"] = "negative"
            if report["actual_coverage"]["additional_checks"]["status"] == "negative" and report["status"] == "passed":
                report["status"] = "negative"
            report["random_seeds"] = [json.loads((run / f"synthetic/trial-{i}/verifier-only/answer.json").read_text(encoding="utf8"))["seed"] for i in range(3)]
    except Exception as exc:
        report.update(status="error", error=repr(exc))
        print(repr(exc),file=sys.stderr)
    report["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save()
    print("RUN",run.relative_to(ROOT).as_posix(),report["status"])
    return 0 if report["status"] == "passed" else 1

if __name__ == "__main__":
    sys.exit(main())
