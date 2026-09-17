"""R015-C: exhaustive PGL(2,29) scan with a literal-hyphen infinity point."""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import platform
import random
import re
import sys
import time
import traceback
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.execution import execute
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES
from lp_lab.synthetic import encode_text


SPEC_PATH = ROOT / "hypotheses/H031-pgl-full-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
HELDOUT_PATH = ROOT / "data/synthetic/heldout.txt"
WORKER_PATH = ROOT / "scripts/attempt22_pgl_worker.py"
HYPOTHESIS = "H031-pgl-full-v1"
MODULUS = 29
INFINITY = 29
PGL_ORDER = 24360
CONTROL_COUNT = 999
ALPHA = 0.01 / 3.0
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 3600
DISCOVERY = tuple(f"LP2/{i}" for i in range(28))
HOLDOUT = tuple([f"LP2/{i}" for i in range(28, 50)] + [f"LP2/{i}" for i in range(51, 56)])
SEEDS = dict(gate_positive=33011531, gate_negative=33011532,
             segment_permutation=33011531, global_s30=33011532)


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf8")


def digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def check_deadline(started: float) -> None:
    if time.monotonic() - started > WALL_SECONDS:
        raise TimeoutError("R015-C wall budget exceeded")


def independent_matrices() -> list[tuple[int, int, int, int]]:
    result = [(a, b, 0, 1) for a in range(1, MODULUS) for b in range(MODULUS)]
    result.extend((a, b, 1, d) for a in range(MODULUS) for d in range(MODULUS)
                  for b in range(MODULUS) if b != (a * d) % MODULUS)
    if len(result) != PGL_ORDER or len(set(result)) != PGL_ORDER:
        raise ValueError("independent PGL representative count changed")
    return result


def independent_image(point: int, matrix: tuple[int, int, int, int]) -> int:
    a, b, c, d = matrix
    determinant = (a * d - b * c) % MODULUS
    if determinant == 0:
        raise ValueError("singular matrix")
    if point == INFINITY:
        return (a * pow(c, MODULUS - 2, MODULUS)) % MODULUS if c else INFINITY
    denominator = (c * point + d) % MODULUS
    if denominator == 0:
        return INFINITY
    return ((a * point + b) * pow(denominator, MODULUS - 2, MODULUS)) % MODULUS


def independent_table(matrix: tuple[int, int, int, int]) -> tuple[int, ...]:
    table = tuple(independent_image(point, matrix) for point in range(INFINITY + 1))
    if sorted(table) != list(range(INFINITY + 1)):
        raise ValueError("matrix is not a projective-line bijection")
    return table


def independent_segments(raw: str) -> tuple[list[list[int]], dict]:
    segments = []
    current = []
    counts = {"runes": 0, "literal_separator": 0, "slash_boundaries": 0,
              "other_hard_boundaries": 0, "formatting_boundaries": 0}
    for char in raw:
        if char in RUNES:
            current.append(RUNES.index(char)); counts["runes"] += 1
        elif char == "-":
            current.append(INFINITY); counts["literal_separator"] += 1
        else:
            if current:
                segments.append(current); current = []
            if char == "/": counts["slash_boundaries"] += 1
            elif char in "\r\n\t ": counts["formatting_boundaries"] += 1
            else: counts["other_hard_boundaries"] += 1
    if current:
        segments.append(current)
    counts.update(segment_count=len(segments), point_count=sum(map(len, segments)))
    return segments, counts


def independent_counts(segments: list[list[int]]) -> dict:
    starts = [0] * 30
    transitions = [[0] * 30 for _ in range(30)]
    points = 0
    for segment in segments:
        if not segment:
            continue
        starts[segment[0]] += 1
        points += len(segment)
        for left, right in zip(segment, segment[1:]):
            transitions[left][right] += 1
    return dict(starts=starts, transitions=transitions, points=points)


def training_segments(text: str) -> list[list[int]]:
    result = []
    for line in text.splitlines():
        words = re.findall(r"[A-Za-z]+", line)
        sequence = []
        for word in words:
            encoded = encode_text(word)
            if not encoded:
                continue
            if sequence:
                sequence.append(INFINITY)
            sequence.extend(encoded)
        if sequence:
            result.append(sequence)
    return result


def independent_model(segments: list[list[int]]) -> dict:
    starts = [0] * 30
    transitions = [[0] * 30 for _ in range(30)]
    for segment in segments:
        if segment:
            starts[segment[0]] += 1
            for left, right in zip(segment, segment[1:]):
                transitions[left][right] += 1
    start_denominator = sum(starts) + 30
    start_weights = [math.log((count + 1) / start_denominator) for count in starts]
    transition_weights = []
    for row in transitions:
        denominator = sum(row) + 30
        transition_weights.append([math.log((count + 1) / denominator) for count in row])
    return dict(start_counts=starts, transition_counts=transitions,
                start_weights=start_weights, transition_weights=transition_weights,
                training_segment_count=len(segments),
                training_point_count=sum(map(len, segments)))


def score_scalar(table: tuple[int, ...], counts: dict, model: dict) -> float:
    if counts["points"] <= 0:
        return float("-inf")
    total = sum(count * model["start_weights"][table[index]]
                for index, count in enumerate(counts["starts"]))
    for left in range(30):
        for right in range(30):
            count = counts["transitions"][left][right]
            if count:
                total += count * model["transition_weights"][table[left]][table[right]]
    return total / counts["points"]


def normalize_counts(counts_list: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    if not counts_list:
        raise ValueError("cannot aggregate empty page set")
    starts = np.zeros(30, dtype=np.float64)
    transitions = np.zeros((30, 30), dtype=np.float64)
    for counts in counts_list:
        denominator = counts["points"]
        starts += np.asarray(counts["starts"], dtype=np.float64) / denominator
        transitions += np.asarray(counts["transitions"], dtype=np.float64) / denominator
    return starts / len(counts_list), transitions.reshape(-1) / len(counts_list)


def prepare_matrix_arrays(matrices: list[tuple[int, int, int, int]], model: dict):
    tables = np.asarray([independent_table(matrix) for matrix in matrices], dtype=np.int16)
    transition_weights = np.asarray(model["transition_weights"], dtype=np.float64)
    pair_weights = np.empty((len(matrices), 900), dtype=np.float64)
    for left in range(30):
        for right in range(30):
            pair_weights[:, left * 30 + right] = transition_weights[tables[:, left], tables[:, right]]
    start_weights = np.asarray(model["start_weights"], dtype=np.float64)
    start_table = np.empty((len(matrices), 30), dtype=np.float64)
    for index in range(30):
        start_table[:, index] = start_weights[tables[:, index]]
    return tables, pair_weights, start_table


def all_matrix_scores(counts_list: list[dict], pair_weights: np.ndarray,
                      start_table: np.ndarray) -> np.ndarray:
    starts, transitions = normalize_counts(counts_list)
    return pair_weights @ transitions + start_table @ starts


def select_matrix(scores: np.ndarray, matrices: list[tuple[int, int, int, int]]) -> tuple[int, float, int]:
    best = max(range(len(matrices)), key=lambda index: (float(scores[index]), tuple(-x for x in matrices[index])))
    best_score = float(scores[best])
    ties = sum(abs(float(score) - best_score) <= TIE_TOLERANCE for score in scores)
    # The max key above is equivalent to descending score and ascending tuple
    # because the final tie check is only diagnostic; make the exact tie rule explicit.
    tied = [index for index, score in enumerate(scores) if abs(float(score) - best_score) <= TIE_TOLERANCE]
    best = min(tied, key=lambda index: matrices[index])
    return best, float(scores[best]), ties


def public_page(page: dict) -> dict:
    return dict(page=page["page"], counts=page["counts"])


def run_worker(run: Path, name: str, public: dict, timeout: int = 900) -> dict:
    folder = run / "worker" / name
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "public.json", public)
    result = execute([sys.executable, "-I", "-S", "-X", "utf8", str(WORKER_PATH)],
                     cwd=ROOT, timeout=timeout, stdin=json.dumps(public, ensure_ascii=False))
    write_json(folder / "execution.json", result)
    (folder / "stdout.json").write_text(result["stdout"], encoding="utf8")
    (folder / "stderr.txt").write_text(result["stderr"], encoding="utf8")
    if result["status"] != "completed":
        if result["status"] == "timeout":
            raise TimeoutError(f"R015-C worker {name} timed out")
        raise RuntimeError(f"R015-C worker {name} failed")
    output = json.loads(result["stdout"])
    if not output.get("read_guard_probe_passed"):
        raise RuntimeError(f"R015-C worker read guard failed: {name}")
    return output


def synthetic_flat_points(text: str) -> list[int]:
    result = []
    for line in text.splitlines():
        words = re.findall(r"[A-Za-z]+", line)
        for word in words:
            encoded = encode_text(word)
            if result and encoded:
                result.append(INFINITY)
            result.extend(encoded)
    return result


def make_gate(matrices: list[tuple[int, int, int, int]], model: dict) -> tuple[list[dict], dict]:
    source = synthetic_flat_points(HELDOUT_PATH.read_text(encoding="utf8"))
    if len(source) < 1200:
        raise ValueError("heldout synthetic source too short for PGL gate")
    lengths = [96, 128, 160, 192, 224]
    positives = []
    private = {}
    for i in range(20):
        length = lengths[i % len(lengths)]
        start = (i * 47 + 11) % (len(source) - length)
        plain = source[start:start + length]
        matrix = matrices[(i * 997 + 19) % len(matrices)]
        table = independent_table(matrix)
        cipher = [table[value] for value in plain]
        expected_inverse = [0] * 30
        for source_value, target_value in enumerate(table):
            expected_inverse[target_value] = source_value
        job_id = f"positive-{i:02d}"
        positives.append(dict(id=job_id, pages=[dict(page=job_id, counts=independent_counts([cipher]))]))
        private[job_id] = dict(kind="positive", start=start, length=length, plaintext=plain,
                               cipher=cipher, matrix=list(matrix), inverse=expected_inverse)
    rng = random.Random(SEEDS["gate_negative"])
    negatives = []
    for i in range(99):
        length = lengths[(i + 2) % len(lengths)]
        start = (i * 31 + 3) % (len(source) - length)
        plain = source[start:start + length]
        if i < 33:
            cipher = [rng.randrange(30) for _ in range(length)]
            kind = "uniform"
        elif i < 66:
            cipher = list(plain); rng.shuffle(cipher); kind = "within_permutation"
        else:
            permutation = list(range(30)); rng.shuffle(permutation)
            cipher = [permutation[value] for value in plain]; kind = "global_s30"
        job_id = f"negative-{i:02d}"
        negatives.append(dict(id=job_id, pages=[dict(page=job_id, counts=independent_counts([cipher]))]))
        private[job_id] = dict(kind=kind, start=start, length=length, cipher=cipher)
    identity = independent_table((1, 0, 0, 1))
    baseline = [score_scalar(identity, independent_counts([source[(i * 47 + 11) % (len(source) - lengths[i % 5]):
                                                              (i * 47 + 11) % (len(source) - lengths[i % 5]) + lengths[i % 5]]]), model)
                for i in range(20)]
    return positives + negatives, dict(private=private, threshold=min(baseline) - 0.25)


def validate_gate(output: dict, private: dict, matrices: list[tuple[int, int, int, int]],
                  tables: np.ndarray, pair_weights: np.ndarray, start_table: np.ndarray,
                  model: dict) -> dict:
    rows = {row["id"]: row for row in output["results"]}
    if set(rows) != set(private):
        raise ValueError("R015-C gate coverage mismatch")
    positives = []
    negatives = []
    for job_id, expected in private.items():
        job = next(row for row in output["results"] if row["id"] == job_id)
        # The public gate batch contains exactly one page. Reconstruct its
        # count vector from the public job retained by the caller below.
        actual = job["selected"]
        if expected["kind"] == "positive":
            exact = actual["mapping"] == expected["inverse"]
            score_ok = actual["score"] >= private["threshold"]
            positives.append(dict(id=job_id, expected_inverse=expected["inverse"], selected=actual["mapping"],
                                  exact_mapping=exact, score=actual["score"], score_ok=score_ok,
                                  status="passed" if exact and score_ok else "negative"))
        else:
            accepted = actual["score"] >= private["threshold"]
            negatives.append(dict(id=job_id, kind=expected["kind"], score=actual["score"],
                                  false_accept=accepted, status="control_collision" if accepted else "negative"))
    positive_passes = sum(row["status"] == "passed" for row in positives)
    false_accepts = sum(row["false_accept"] for row in negatives)
    return dict(status="passed" if positive_passes >= 18 and false_accepts == 0 else "failed",
                threshold=private["threshold"], positive_passes=positive_passes,
                positive_count=len(positives), negative_false_accepts=false_accepts,
                negative_count=len(negatives), positives=positives, negatives=negatives)


def make_control_pages(pages: list[dict], family: str, replicate: int) -> tuple[list[dict], str]:
    rng = random.Random(SEEDS[family] + replicate)
    result = []
    if family == "segment_permutation":
        for page in pages:
            segments = []
            for segment in page["segments"]:
                copy = list(segment); rng.shuffle(copy); segments.append(copy)
            result.append(dict(page=page["page"], segments=segments,
                               counts=independent_counts(segments)))
    elif family == "global_s30":
        permutation = list(range(30)); rng.shuffle(permutation)
        for page in pages:
            segments = [[permutation[value] for value in segment] for segment in page["segments"]]
            result.append(dict(page=page["page"], segments=segments,
                               counts=independent_counts(segments)))
    else:
        raise ValueError(f"unknown R015-C control family {family}")
    return result, digest([page["counts"] for page in result])


def holm(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    result = [1.0] * len(values)
    running = 0.0
    for rank, (index, value) in enumerate(ordered):
        running = max(running, min(1.0, value * (len(values) - rank)))
        result[index] = running
    return result


def p_high(value: float, controls: list[float]) -> float:
    return (1 + sum(control >= value - TIE_TOLERANCE for control in controls)) / (len(controls) + 1)


def holdout_statistics(observed: list[float], controls: list[list[float]]) -> list[dict]:
    if not controls:
        return []
    raw = [p_high(value, [row[i] for row in controls]) for i, value in enumerate(observed)]
    adjusted = holm(raw)
    zs = []
    for i, value in enumerate(observed):
        sample = [row[i] for row in controls]
        mean = sum(sample) / len(sample)
        variance = sum((x - mean) ** 2 for x in sample) / len(sample)
        std = math.sqrt(variance)
        zs.append((value - mean) / std if std > 0 else 0.0)
    max_control = [max(((row[i] - sum(control[i] for control in controls) / len(controls)) /
                        (math.sqrt(sum((control[i] - sum(c[i] for c in controls) / len(controls)) ** 2 for c in controls) / len(controls)) or 1.0)
                        for i in range(len(observed))), default=0.0) for row in controls]
    max_p = [(1 + sum(control >= z - TIE_TOLERANCE for control in max_control)) / (len(controls) + 1)
             for z in zs]
    return [dict(index=i, observed=observed[i], raw_p=raw[i], holm_p=adjusted[i],
                 z=zs[i], max_t_p=max_p[i]) for i in range(len(observed))]


def archive_run(run: Path, snapshot: dict) -> dict:
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / name for name in snapshot["files"]]
    for directory in ("data", "sources", "hypotheses", "research"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    paths.extend(path for path in run.rglob("*") if path.is_file() and path != archive)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive), bytes=archive.stat().st_size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("R015-C run must be inside runs/")
    run.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc)
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis=HYPOTHESIS, attempt="auto-cycle R015-C", status="running",
                  started_at_utc=started_at.isoformat(), python=sys.version, executable=sys.executable,
                  platform=platform.platform(), code_version=snapshot, controls_completed=0,
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        for source in spec["sources"]:
            if "sha256" in source and sha256(ROOT / source["path"]) != source["sha256"]:
                raise ValueError(f"R015-C source hash changed: {source['path']}")
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
        pages = []
        for page in corpus["pages"]:
            segments, metadata = independent_segments(page["raw"])
            counts = independent_counts(segments)
            pages.append(dict(page=page["page"], raw=page["raw"], raw_sha256=page["raw_sha256"],
                              source=page["source"], source_sha256=page["source_sha256"],
                              segments=segments, counts=counts, metadata=metadata))
        if [page["page"] for page in pages if page["counts"]["points"] == 0] != ["LP2/50"]:
            raise ValueError("R015-C point applicability changed")
        applicable = [page for page in pages if page["counts"]["points"] > 0]
        if len(applicable) != 55 or sum(page["metadata"]["runes"] for page in applicable) != 12956:
            raise ValueError("R015-C rune coverage changed")
        model = independent_model(training_segments(TRAIN_PATH.read_text(encoding="utf8")))
        matrices = independent_matrices()
        tables, pair_weights, start_table = prepare_matrix_arrays(matrices, model)
        gate_jobs, gate_private = make_gate(matrices, model)
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH), corpus_sha256=sha256(CORPUS_PATH),
                      training_sha256=sha256(TRAIN_PATH), heldout_sha256=sha256(HELDOUT_PATH),
                      source_files_verified=source_count, code_version=snapshot,
                      page_order=[page["page"] for page in pages], discovery=list(DISCOVERY), holdout=list(HOLDOUT),
                      excluded=["LP2/50"], separator_contract="literal '-' -> infinity(29); slash/whitespace/other literals are boundaries",
                      matrices_count=len(matrices), affine_count=812, non_affine_count=23548,
                      model=dict(training_segment_count=model["training_segment_count"], training_point_count=model["training_point_count"],
                                 start_counts=model["start_counts"], transition_counts=model["transition_counts"], digest=digest(model)),
                      gate=dict(positive_count=20, negative_count=99, threshold=gate_private["threshold"], seeds=SEEDS),
                      controls=dict(count=CONTROL_COUNT, families=["segment_permutation", "global_s30"], seeds=SEEDS),
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE, wall_seconds=WALL_SECONDS,
                      point_count=sum(page["counts"]["points"] for page in applicable),
                      rune_count=sum(page["metadata"]["runes"] for page in applicable))
        write_json(run / "frozen.json", frozen)
        write_json(run / "verifier-only" / "gate-answers.json", gate_private)
        gate_public = dict(schema=1, hypothesis=HYPOTHESIS,
                           model=dict(start_weights=model["start_weights"], transition_weights=model["transition_weights"]),
                           jobs=gate_jobs)
        gate_output = run_worker(run, "gate", gate_public, timeout=1200)
        # The worker's selected result is independently checked below using
        # the exact public count vectors, not the private plaintext.
        gate_by_id = {job["id"]: job for job in gate_jobs}
        gate_checks = []
        for row in gate_output["results"]:
            public_page_counts = gate_by_id[row["id"]]["pages"][0]["counts"]
            counts = dict(starts=public_page_counts["starts"], transitions=public_page_counts["transitions"], points=public_page_counts["points"])
            scores = pair_weights @ np.asarray(counts["transitions"], dtype=np.float64).reshape(-1) + start_table @ np.asarray(counts["starts"], dtype=np.float64)
            scores /= counts["points"]
            selected_index, selected_score, ties = select_matrix(scores, matrices)
            actual = row["selected"]
            if actual["matrix"] != list(matrices[selected_index]) or not math.isclose(actual["score"], selected_score, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError(f"R015-C gate independent selection mismatch {row['id']}")
            gate_checks.append(dict(id=row["id"], matrix=actual["matrix"], score=actual["score"],
                                    ties=ties, independent=True))
        positives = []
        negatives = []
        for row in gate_checks:
            expected = gate_private[row["id"]]
            actual = row["matrix"]
            if expected["kind"] == "positive":
                exact = [independent_image(point, tuple(actual)) for point in range(30)] == expected["inverse"]
                score_ok = row["score"] >= gate_private["threshold"]
                positives.append(dict(id=row["id"], expected_inverse=expected["inverse"], selected=actual,
                                      exact_mapping=exact, score=row["score"], score_ok=score_ok,
                                      status="passed" if exact and score_ok else "negative"))
            else:
                accepted = row["score"] >= gate_private["threshold"]
                negatives.append(dict(id=row["id"], kind=expected["kind"], score=row["score"],
                                      false_accept=accepted, status="control_collision" if accepted else "negative"))
        positive_passes = sum(row["status"] == "passed" for row in positives)
        false_accepts = sum(row["false_accept"] for row in negatives)
        gate = dict(status="passed" if positive_passes >= 18 and false_accepts == 0 else "failed",
                    threshold=gate_private["threshold"], positive_passes=positive_passes,
                    positive_count=len(positives), negative_false_accepts=false_accepts,
                    negative_count=len(negatives), positives=positives, negatives=negatives,
                    independent_checks=gate_checks)
        write_json(run / "gate.json", gate)
        record.update(source_files_verified=source_count, frozen_sha256=sha256(run / "frozen.json"),
                      gate_status=gate["status"], gate_positive_passes=positive_passes,
                      gate_negative_false_accepts=false_accepts)
        write_json(run / "record.json", record)
        if gate["status"] != "passed":
            record.update(status="inconclusive", reason="power_gate_failed",
                          finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          elapsed_seconds=time.monotonic() - started,
                          reproduction_bundle=archive_run(run, snapshot))
            write_json(run / "record.json", record)
            print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"], "gate": gate["status"]}, ensure_ascii=False))
            return 0

        discovery_pages = [page for page in applicable if page["page"] in DISCOVERY]
        holdout_pages = [page for page in applicable if page["page"] in HOLDOUT]
        discovery_scores = all_matrix_scores([page["counts"] for page in discovery_pages], pair_weights, start_table)
        selected_index, selected_score, ties = select_matrix(discovery_scores, matrices)
        selected_matrix = matrices[selected_index]
        selected_table = tuple(int(value) for value in tables[selected_index])
        holdout_scores = [score_scalar(selected_table, page["counts"], model) for page in holdout_pages]
        per_page_top = []
        for page in applicable:
            scores = pair_weights @ np.asarray(page["counts"]["transitions"], dtype=np.float64).reshape(-1) + start_table @ np.asarray(page["counts"]["starts"], dtype=np.float64)
            scores /= page["counts"]["points"]
            top_index, top_score, top_ties = select_matrix(scores, matrices)
            per_page_top.append(dict(page=page["page"], selected_matrix=list(matrices[top_index]),
                                     score=top_score, ties=top_ties,
                                     selected_global_score=score_scalar(selected_table, page["counts"], model),
                                     point_count=page["counts"]["points"], metadata=page["metadata"]))
        formal_public = dict(schema=1, hypothesis=HYPOTHESIS,
                             model=dict(start_weights=model["start_weights"], transition_weights=model["transition_weights"]),
                             pages=[public_page(page) for page in discovery_pages])
        formal_output = run_worker(run, "formal-observed", formal_public, timeout=1200)
        worker_selected = formal_output["results"][0]["selected"]
        if worker_selected["matrix"] != list(selected_matrix) or not math.isclose(worker_selected["score"], selected_score, rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("R015-C worker/independent discovery selection mismatch")
        independent_validation = dict(status="passed", matrix_count=len(matrices),
                                      sample_checks=[], inverse_checks=0, page_checks=len(applicable))
        for index in list(range(0, len(matrices), 137)) + [selected_index]:
            matrix = matrices[index]
            table = independent_table(matrix)
            inverse = [0] * 30
            for source_value, target_value in enumerate(table): inverse[target_value] = source_value
            if [inverse[value] for value in table] != list(range(30)):
                raise ValueError("R015-C inverse mapping check failed")
            independent_validation["sample_checks"].append(dict(matrix=list(matrix),
                                                                 images=list(table),
                                                                 pole=table[(-matrix[3]) % 29] if matrix[2] == 1 else None))
            independent_validation["inverse_checks"] += 1
        if independent_image(25, (2, 3, 1, 4)) != INFINITY or independent_image(INFINITY, (2, 3, 1, 4)) != 2:
            raise ValueError("R015-C explicit pole check failed")
        write_json(run / "independent-verification.json", independent_validation)
        write_json(run / "observed.json", dict(discovery=dict(matrix=list(selected_matrix), score=selected_score, ties=ties),
                                                holdout=dict(matrix=list(selected_matrix), scores=holdout_scores, pages=[page["page"] for page in holdout_pages]),
                                                per_page_top=per_page_top, matrices_count=len(matrices)))

        controls = {"segment_permutation": [], "global_s30": []}
        control_holdout = {"segment_permutation": [], "global_s30": []}
        for family in controls:
            for replicate in range(CONTROL_COUNT):
                check_deadline(started)
                controlled, control_digest = make_control_pages(applicable, family, replicate)
                d_pages = [page for page in controlled if page["page"] in DISCOVERY]
                h_pages = [page for page in controlled if page["page"] in HOLDOUT]
                d_scores = all_matrix_scores([page["counts"] for page in d_pages], pair_weights, start_table)
                control_index, control_score, control_ties = select_matrix(d_scores, matrices)
                control_table = tuple(int(value) for value in tables[control_index])
                h_scores = [score_scalar(control_table, page["counts"], model) for page in h_pages]
                h_score = sum(h_scores) / len(h_scores)
                row = dict(replicate=replicate, input_sha256=control_digest,
                           discovery_score=control_score, selected_matrix=list(matrices[control_index]),
                           ties=control_ties, holdout_score=h_score, holdout_scores=h_scores)
                controls[family].append(row)
                control_holdout[family].append(h_scores)
                if (replicate + 1) % 25 == 0:
                    write_json(run / "control-results.partial.json", controls)
        write_json(run / "control-results.json", controls)
        record["controls_completed"] = CONTROL_COUNT * 2
        write_json(run / "record.json", record)
        statistics = dict(status="negative", verification_status="passed", leads=[],
                          coverage=dict(pages=55, runes=12956, points=sum(page["counts"]["points"] for page in applicable),
                                        discovery_pages=len(discovery_pages), holdout_pages=len(holdout_pages),
                                        matrices=len(matrices), controls_per_family=CONTROL_COUNT), families={},
                          negative_scope="Only the fixed literal-hyphen infinity contract, common PGL matrix, scorer, D/H partition and two declared control families.")
        for family in controls:
            d_values = [row["discovery_score"] for row in controls[family]]
            h_values = [row["holdout_score"] for row in controls[family]]
            page_rows = holdout_statistics(holdout_scores, control_holdout[family])
            for index, row in enumerate(page_rows): row["page"] = holdout_pages[index]["page"]
            statistics["families"][family] = dict(discovery_p=p_high(selected_score, d_values),
                                                    holdout_p=p_high(sum(holdout_scores) / len(holdout_scores), h_values),
                                                    page_statistics=page_rows,
                                                    controls_completed=len(controls[family]))
        family_page_sets = []
        for family in statistics["families"]:
            family_page_sets.append({row["page"] for row in statistics["families"][family]["page_statistics"]
                                     if row["holm_p"] <= ALPHA and row["max_t_p"] <= ALPHA})
        common = set.intersection(*family_page_sets) if family_page_sets else set()
        if all(statistics["families"][family]["discovery_p"] <= ALPHA and statistics["families"][family]["holdout_p"] <= ALPHA
               for family in statistics["families"]) and len(common) >= 2:
            statistics["status"] = "inconclusive"
            statistics["leads"] = sorted(common)
        write_json(run / "statistics.json", statistics)
        record.update(status=statistics["status"], result=dict(selected_matrix=list(selected_matrix),
                      discovery_score=selected_score, leads=statistics["leads"]), actual_coverage=statistics["coverage"])
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("code changed during R015-C run")
        record["reproduction_bundle"] = archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc),
                      finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - started)
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    write_json(run / "record.json", record)
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"],
                      "controls_completed": record.get("controls_completed", 0), "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
