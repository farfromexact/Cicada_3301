from pathlib import Path
import argparse
from collections import Counter
import json
import secrets
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.synthetic import encode_text, generate, verify
from lp_lab.provenance import sha256, code_snapshot
from lp_lab.execution import execute

def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+"\n", encoding="utf8")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replay", type=Path, help="Prior benchmark directory; seeds read only by generator")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    frozen = code_snapshot(ROOT)
    train_path, held_path = [ROOT / f"data/synthetic/{name}.txt" for name in ("training", "heldout")]
    train = encode_text(train_path.read_text(encoding="utf8"))
    held = encode_text(held_path.read_text(encoding="utf8"))
    assert sha256(train_path) != sha256(held_path)
    counts = Counter(train)
    write(args.out / "frozen.json", dict(code=frozen, training_sha256=sha256(train_path),
          heldout_sha256=sha256(held_path), hypothesis_sha256=sha256(ROOT / "hypotheses/H000-baseline.json"),
          statement="Profile, code and criteria frozen before drawing keys; heldout not used in scoring"))
    reports = []
    for trial in range(3):
        folder = args.out / f"trial-{trial}"
        folder.mkdir()
        private = folder / "verifier-only"
        private.mkdir()
        seed = (json.loads((args.replay / f"trial-{trial}/verifier-only/answer.json").read_text(encoding="utf8"))["seed"]
                if args.replay else secrets.randbits(128))
        cipher, answer = generate(held, seed)
        write(private / "answer.json", answer)
        public = dict(schema=1, ciphertext=cipher, training_counts=[counts[i] for i in range(29)], offset_max=31, shift_max=28)
        write(folder / "public.json", public)
        # Isolated interpreter; no site, no project PYTHONPATH, clean cwd, stdin is the only data channel.
        execution = execute([sys.executable, "-I", "-S", "-X", "utf8", str(ROOT / "scripts/search_worker.py")],
                            cwd=folder, timeout=30, stdin=json.dumps(public))
        write(folder / "execution.json", execution)
        (folder / "stdout.json").write_text(execution["stdout"], encoding="utf8")
        (folder / "stderr.txt").write_text(execution["stderr"], encoding="utf8")
        if execution["status"] == "completed":
            candidate = json.loads(execution["stdout"])
            result = verify(answer, candidate, cipher)
            result.update(covered=candidate["covered"], score_gap=candidate["score_gap"],
                          read_guard_probe_passed=candidate["read_guard_probe_passed"])
            if candidate["covered"] != 928 or not candidate["read_guard_probe_passed"]:
                result["status"] = "error"
        else:
            result = dict(status=execution["status"], covered=None, note="Incomplete/unknown coverage is not a negative")
        write(folder / "verification.json", result)
        reports.append(result)
    if code_snapshot(ROOT) != frozen:
        raise RuntimeError("Code changed during the benchmark")
    statuses = {r["status"] for r in reports}
    status = "error" if "error" in statuses else "timeout" if "timeout" in statuses else "negative" if "negative" in statuses else "passed"
    summary = dict(trials=reports, training_runes=len(train), heldout_runes=len(held),
                   status=status,
                   replay_of=str(args.replay) if args.replay else None)
    write(args.out / "summary.json", summary)
    print(json.dumps(summary))
    # A completed scientific negative is a successful program execution.
    return 0 if status in ("passed", "negative") else 1

if __name__ == "__main__":
    sys.exit(main())
