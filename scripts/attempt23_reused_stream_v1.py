"""H027 stage-one capability gate; formal LP2 is never dispatched on failure."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import random
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.execution import execute
from lp_lab.runes import RUNES
from lp_lab.synthetic import encode_text

HYPOTHESIS = "H027-adjacent-reused-stream-v1"
SPEC = ROOT / "hypotheses/H027-adjacent-reused-stream-v1.json"
WORKER = ROOT / "scripts/attempt23_reused_stream_worker_v1.py"
CORPUS = ROOT / "data/attempt1-corpus-v1.json"
TRAIN = ROOT / "data/synthetic/training.txt"
HELDOUT = ROOT / "data/synthetic/heldout.txt"
REVIEW = ROOT / "reviews/H027-adjacent-reused-stream-v1.md"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")


def training_counts():
    text = encode_text(TRAIN.read_text(encoding="utf8"))
    unigrams = [text.count(i) for i in range(29)]
    bigrams = [[0] * 29 for _ in range(29)]
    for a, b in zip(text, text[1:]):
        bigrams[a][b] += 1
    return unigrams, bigrams


def verifier_model(u, counts):
    """Independent count-space difference convolution, normalized only at end."""
    smoothed = [[v + 1 for v in row] for row in counts]
    pi = [(v + 1) / (sum(u) + 29) for v in u]
    trans = [[v / sum(row) for v in row] for row in smoothed]
    dpi = [0.0] * 29
    dcounts = [[0] * 29 for _ in range(29)]
    for x in range(29):
        for y in range(29):
            dpi[(x - y) % 29] += pi[x] * pi[y]
    for x0 in range(29):
        for x1 in range(29):
            value = smoothed[x0][x1]
            for y0 in range(29):
                a = (x0 - y0) % 29
                for y1 in range(29):
                    dcounts[a][(x1 - y1) % 29] += value * smoothed[y0][y1]
    dt = [[v / sum(row) for v in row] for row in dcounts]
    return dict(pi=pi, t=trans, dpi=dpi, dt=dt)


def backward_optimum(d, model, previous=None):
    """Backward scalar Bellman recursion, independent of worker forward Viterbi."""
    logs = [[math.log(v) for v in row] for row in model["t"]]
    suffix = [0.0] * 29
    for i in range(len(d) - 2, -1, -1):
        future = []
        for a in range(29):
            b = (a - d[i]) % 29
            future.append(max(logs[a][n] + logs[b][(n - d[i + 1]) % 29] + suffix[n] for n in range(29)))
        suffix = future
    if previous is None:
        return max(math.log(model["pi"][a]) + math.log(model["pi"][(a - d[0]) % 29]) + suffix[a] for a in range(29))
    return max(logs[previous[0]][a] + logs[previous[1]][(a - d[0]) % 29] + suffix[a] for a in range(29))


def path_objective(a, b, model, previous=None):
    if previous is None:
        score = math.log(model["pi"][a[0]]) + math.log(model["pi"][b[0]])
    else:
        score = math.log(model["t"][previous[0]][a[0]]) + math.log(model["t"][previous[1]][b[0]])
    for path in (a, b):
        for left, right in zip(path, path[1:]):
            score += math.log(model["t"][left][right])
    return score


def verify_output(public, output, model):
    if set(output) != {"status", "read_guard_probe_passed", "jobs"} or output["status"] != "completed" or output["read_guard_probe_passed"] is not True:
        raise ValueError("H027 invalid worker completion")
    if [j["id"] for j in public["jobs"]] != [j["id"] for j in output["jobs"]]:
        raise ValueError("H027 missing/reordered job")
    count = 0
    for job, row in zip(public["jobs"], output["jobs"]):
        n, split = len(job["a"]), 2 * len(job["a"]) // 3
        if set(row) != {"id", "difference", "split", "a", "b", "key_a", "key_b", "viterbi_scores", "log_bf"} or row["split"] != split:
            raise ValueError("H027 output field/split mismatch")
        for field in ("a", "b", "difference", "key_a", "key_b"):
            if len(row[field]) != n or any(type(v) is not int or not 0 <= v < 29 for v in row[field]):
                raise ValueError("H027 invalid output length/value")
        d = [(job["a"][i] - job["b"][i]) % 29 for i in range(n)]
        if d != row["difference"] or any((a - b) % 29 != v for a, b, v in zip(row["a"], row["b"], d)):
            raise ValueError("H027 difference identity mismatch")
        if row["key_a"] != row["key_b"]:
            raise ValueError("H027 recovered streams differ")
        for side in ("a", "b"):
            if any((p + k) % 29 != c for p, k, c in zip(row[side], row["key_" + side], job[side])):
                raise ValueError("H027 roundtrip mismatch")
        for j, (start, stop, previous) in enumerate(((0, split, None), (split, n, (row["a"][split - 1], row["b"][split - 1])))):
            objective = path_objective(row["a"][start:stop], row["b"][start:stop], model, previous)
            optimum = backward_optimum(d[start:stop], model, previous)
            if not math.isclose(objective, optimum, abs_tol=1e-8) or not math.isclose(row["viterbi_scores"][j], optimum, abs_tol=1e-8):
                raise ValueError("H027 path is not Bellman optimal")
        terms = [math.log(29 * model["dpi"][d[0]])]
        terms.extend(math.log(29 * model["dt"][d[i - 1]][d[i]]) for i in range(1, n))
        scores = [sum(terms[:split]), sum(terms[split:])]
        if any(not math.isclose(a, b, abs_tol=1e-8) for a, b in zip(scores, row["log_bf"])):
            raise ValueError("H027 difference likelihood mismatch")
        count += n
    return dict(status="passed", jobs=len(public["jobs"]), aligned_positions=count, bellman_segments=2 * len(public["jobs"]), algorithm="independent backward Bellman, count-space convolution, per-rune equations and roundtrip")


def prefix_metadata():
    corpus = json.loads(CORPUS.read_text(encoding="utf8"))
    pages = corpus["pages"]
    if [p["page"] for p in pages] != [f"LP2/{i}" for i in range(56)]:
        raise ValueError("Corpus page universe/order drift")
    metadata, source_paths = [], []
    for page in pages:
        if hashlib.sha256(page["raw"].encode("utf8")).hexdigest() != page["raw_sha256"] or sha(ROOT / page["source"]) != page["source_sha256"]:
            raise ValueError("Corpus source drift")
        prefix, positions, stop = [], [], None
        for offset, char in enumerate(page["raw"]):
            if char.isascii() and char.isalnum():
                stop = offset
                break
            if char in RUNES:
                prefix.append(RUNES.index(char))
                positions.append(offset)
            elif 0x16A0 <= ord(char) <= 0x16FF:
                raise ValueError("Unknown rune glyph")
        metadata.append(dict(page=page["page"], original_rune_count=page["rune_count"], legal_prefix_count=len(prefix), original_char_positions=positions, ascii_barrier_char_offset=stop, excluded_runes=page["rune_count"] - len(prefix), raw_sha256=page["raw_sha256"], source=page["source"], source_sha256=page["source_sha256"], prefix=prefix))
        source_paths.append(ROOT / page["source"])
    pairs = []
    for a, b in zip(metadata, metadata[1:]):
        n = min(a["legal_prefix_count"], b["legal_prefix_count"])
        pairs.append(dict(pair=a["page"] + "::" + b["page"], overlap=n, applicable=n >= 30, reason="original adjacent zero-origin prefixes" if n >= 30 else "no legal 30-rune overlap before ASCII grid barrier", unpaired_tails=[a["legal_prefix_count"] - n, b["legal_prefix_count"] - n], status="not_dispatched_pending_gate"))
    for page in metadata:
        del page["prefix"]
    return dict(pages=metadata, pairs=pairs, applicable_pairs=sum(p["applicable"] for p in pairs), raw_corpus_runes=sum(p["original_rune_count"] for p in metadata), note="Metadata only; no LP2 statistic or candidate computed"), source_paths


def synthetic_public(spec, u, b):
    heldout = encode_text(HELDOUT.read_text(encoding="utf8"))
    rng = random.Random(spec["synthetic_gate"]["seed"])
    lengths = spec["synthetic_gate"]["lengths"]
    jobs, answers = [], {}
    for index in range(119):
        positive = index < 20
        i = index if positive else (index - 20) % 20
        n = lengths[i]
        pa = heldout[i * 13:i * 13 + n]
        pb = heldout[598 + i * 13:598 + i * 13 + n]
        if len(pa) != n or len(pb) != n:
            raise ValueError("Frozen natural windows too short")
        ka = [rng.randrange(29) for _ in range(n)]
        kb = list(ka) if positive else [rng.randrange(29) for _ in range(n)]
        job_id = f"pair-{index:03d}"
        jobs.append(dict(id=job_id, a=[(p + k) % 29 for p, k in zip(pa, ka)], b=[(p + k) % 29 for p, k in zip(pb, kb)]))
        answers[job_id] = dict(kind="same_stream" if positive else "independent_stream", a=pa, b=pb, key_a=ka, key_b=kb, source_windows=[i * 13, 598 + i * 13])
    return dict(schema=1, hypothesis=HYPOTHESIS, unigram_counts=u, bigram_counts=b, jobs=jobs), answers


def assess_gate(output, answers):
    rows = []
    for row in output["jobs"]:
        truth = answers[row["id"]]
        n, split = len(row["a"]), row["split"]
        accuracy = {}
        for side in ("a", "b"):
            for label, start, stop in (("discovery", 0, split), ("holdout", split, n)):
                accuracy[side + "_" + label] = sum(p == q for p, q in zip(row[side][start:stop], truth[side][start:stop])) / (stop - start)
        detected = all(v >= math.log(100) for v in row["log_bf"])
        recovered = all(v >= 0.60 for v in accuracy.values())
        rows.append(dict(id=row["id"], kind=truth["kind"], log_bf=row["log_bf"], accuracy=accuracy, detected=detected, recovery_passed=recovered, accepted=detected and recovered, exact_plaintext=row["a"] == truth["a"] and row["b"] == truth["b"], exact_key=row["key_a"] == truth["key_a"] and row["key_b"] == truth["key_b"]))
    positive = [r for r in rows if r["kind"] == "same_stream"]
    negative = [r for r in rows if r["kind"] == "independent_stream"]
    recovered = sum(r["accepted"] for r in positive)
    false = sum(r["detected"] for r in negative)
    return dict(status="passed" if recovered >= 18 and false == 0 else "inconclusive", positive_accepted=recovered, positive_detected=sum(r["detected"] for r in positive), positive_recovery_passed=sum(r["recovery_passed"] for r in positive), positive_exact_plaintext=sum(r["exact_plaintext"] for r in positive), positive_exact_key=sum(r["exact_key"] for r in positive), negative_false_accepts=false, positive_count=20, negative_count=99, rows=rows)


def archive(run, paths):
    target = run / "reproduction-bundle.zip"
    files = sorted(set(paths + [p for p in run.rglob("*") if p.is_file() and p != target]))
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:
            raise ValueError("H027 archive CRC failed")
        for path in files:
            if hashlib.sha256(z.read(path.relative_to(ROOT).as_posix())).hexdigest() != sha(path):
                raise ValueError("H027 archive byte check failed")
    return dict(path=target.relative_to(ROOT).as_posix(), sha256=sha(target), members=len(files), crc="passed", byte_checks="passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="runs/20260919-H027-v1")
    args = ap.parse_args()
    run = ROOT / args.run
    if run.exists():
        raise FileExistsError("H027 runs are append-only; choose a new run directory")
    run.mkdir(parents=True)
    started = time.monotonic()
    spec = json.loads(SPEC.read_text(encoding="utf8"))
    deadline = started + spec["budget"]["wall_seconds"]
    record = dict(schema=1, hypothesis=HYPOTHESIS, stage="synthetic_gate", started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), status="error", lp2_dispatched=False, lp2_statistic_count=0, controls_completed=0, leads=[], unsolved_page_candidates=[])
    paths = [SPEC, WORKER, Path(__file__), CORPUS, TRAIN, HELDOUT, ROOT / "src/lp_lab/runes.py", ROOT / "src/lp_lab/synthetic.py", ROOT / "src/lp_lab/execution.py", ROOT / "tests/test_reused_stream.py", ROOT / "reviews/auto-cycle-009.md", ROOT / "research/METHOD.md", ROOT / "research/methods.json", ROOT / "AGENTS.md"]
    try:
        coverage, raw_paths = prefix_metadata()
        paths += raw_paths
        u, b = training_counts()
        public, answers = synthetic_public(spec, u, b)
        write(run / "public-gate.json", public)
        write(run / "verifier-only/answers.json", answers)
        write(run / "coverage.json", coverage)
        write(run / "frozen.json", dict(frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), specification=spec, source_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(paths))}, public_sha256=sha(run / "public-gate.json"), private_sha256=sha(run / "verifier-only/answers.json"), coverage_sha256=sha(run / "coverage.json"), python=sys.version, lp2_scores_seen=False))
        print("H027 frozen; dispatching119 gate pairs only", flush=True)
        execution = execute([sys.executable, "-I", "-S", str(WORKER)], cwd=ROOT, timeout=max(1, deadline - time.monotonic()), stdin=json.dumps(public))
        write(run / "worker-gate-execution.json", execution)
        (run / "worker-gate-stdout.json").write_text(execution["stdout"], encoding="utf8")
        (run / "worker-gate-stderr.txt").write_text(execution["stderr"], encoding="utf8")
        if execution["status"] != "completed":
            if execution["status"] == "timeout":
                raise TimeoutError("H027 worker deadline")
            raise RuntimeError("H027 worker failed; preserved execution logs")
        output = json.loads(execution["stdout"])
        model = verifier_model(u, b)
        verification = verify_output(public, output, model)
        write(run / "independent-verification.json", verification)
        gate = assess_gate(output, answers)
        write(run / "gate.json", gate)
        if time.monotonic() >= deadline:
            raise TimeoutError("H027 deadline after gate verification")
        record.update(status=gate["status"], gate_summary={k: v for k, v in gate.items() if k != "rows"}, independent_verification="passed", applicable_pairs=coverage["applicable_pairs"], stop_reason="gate_failed_no_lp2" if gate["status"] != "passed" else "gate_passed_formal_implementation_pending")
        for pair in coverage["pairs"]:
            pair["status"] = "not_executed_gate_failure" if pair["applicable"] and gate["status"] != "passed" else "not_executed" if pair["applicable"] else "not_applicable"
        write(run / "coverage-final.json", coverage)
        positive = [r for r in gate["rows"] if r["kind"] == "same_stream"]
        acc = {key: sum(r["accuracy"][key] for r in positive) / len(positive) for key in positive[0]["accuracy"]}
        text = "# H027 相邻页复用流：合成恢复能力门控\n\n日期：2026-09-19。规范、代码、训练计数、公开密文及私有答案在运行前冻结；未计算LP2分数。\n\n"
        text += f"结果为 **{record['status']}**。20个同流自然文本正例，差分发现/留出统计门通过 {gate['positive_detected']}/20，四项逐符文恢复门通过 {gate['positive_recovery_passed']}/20，二者同时通过 {gate['positive_accepted']}/20（要求至少18）；99个独立流负例误收 {gate['negative_false_accepts']}/99。完整双明文和钥匙精确恢复分别为 {gate['positive_exact_plaintext']}/20、{gate['positive_exact_key']}/20。\n\n"
        text += "两明文的平均精确符文恢复率（逐样本等权）：" + "，".join(f"{k}={v:.4%}" for k, v in acc.items()) + "。这是真值逐符文比较，未使用语言补写或拼写修正。\n\n"
        text += "模型固定使用1291符文训练文本的add-one unigram/bigram；29状态Viterbi先解前2/3，再固定其末状态解后1/3。后1/3检验的是固定差分模型的条件密度预测，不能当成未知钥匙后缀的独立预测。任何共同钥匙都可以由输出明文反推，反向一致本身不构成破解。\n\n"
        text += f"全部119个公开job经文件/进程/网络读取禁用的worker执行；独立反向Bellman、差分卷积、逐符文方程及回加密验证通过。20正例取自1196符文heldout，单个job两窗口不重叠，但不同job的窗口有重叠，故这些计数不是独立重复试验的总体置信区间。\n\n"
        text += f"LP2原始0..55页和55个相邻对已列元数据覆盖；符合页首零偏移、30符文重叠及ASCII网格硬屏障的对数为{coverage['applicable_pairs']}。网格不跳过消费；LP2/49仅用前网格段，LP2/50与页首网格的51没有合法前缀。正式LP2 dispatch=0，统计量=0，置换对照=0；未尝试页对没有写成negative。\n\n"
        text += "门失败即止，不更改阈值、偏移、平滑或训练文本补考。结论只涉及本训练模型下的恢复能力；不排除相邻页实际复用流，也不构成整个H027密码机制的阴性。下一步应切换到有可推导钥匙或独立明文锚点的新机制。\n\n"
        text += f"运行：[record.json](../{args.run}/record.json)；逐例结果：[gate.json](../{args.run}/gate.json)；私有精确真值、公开密文、原始日志、来源SHA-256、运行时和规范均保留在运行及复现包中。\n"
        REVIEW.write_text(text, encoding="utf8")
        paths.append(REVIEW)
    except TimeoutError as exc:
        record.update(status="timeout", stop_reason=str(exc))
        (run / "runner-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    except Exception as exc:
        record.update(status="error", stop_reason=repr(exc))
        (run / "runner-error.txt").write_text(traceback.format_exc(), encoding="utf8")
    record.update(elapsed_seconds=time.monotonic() - started, finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    write(run / "record.json", record)
    write(run / "checkpoint.json", dict(status="complete" if record["status"] not in ("error", "timeout") else record["status"], gate_completed=(run / "gate.json").exists(), lp2_dispatched=False, control_completed=0, frozen_sha256=sha(run / "frozen.json") if (run / "frozen.json").exists() else None))
    archive_info = archive(run, [p for p in paths if p.exists()])
    write(run / "archive-check.json", archive_info)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return 1 if record["status"] in ("error", "timeout") else 0


if __name__ == "__main__":
    raise SystemExit(main())
