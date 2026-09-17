"""R015-A: finite, source-backed DSL with a two-part LP2 holdout.

The runner owns source loading, synthetic private answers, controls and the
independent arithmetic path.  The guarded worker sees only public rune
streams and the frozen language-model weights.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import math
import platform
import random
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lp_lab.execution import execute
from lp_lab.provenance import code_snapshot, sha256, verify_sources
from lp_lab.runes import RUNES
from lp_lab.r015_dsl import (DIVINITY, STATE_OPERATORS, apply_symbol_permutation,
                             build_language_model, enumerate_recipes, encrypt_recipe,
                             primes)


SPEC_PATH = ROOT / "hypotheses/H029-finite-dsl-v1.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
TRAIN_PATH = ROOT / "data/synthetic/training.txt"
HELDOUT_PATH = ROOT / "data/synthetic/heldout.txt"
WORKER_PATH = ROOT / "scripts/attempt20_dsl_worker.py"
HYPOTHESIS = "H029-finite-dsl-v1"
CONTROL_COUNT = 999
ALPHA = 0.01 / 3.0
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 1800
DISCOVERY = tuple(f"LP2/{i}" for i in range(28))
HOLDOUT = tuple([f"LP2/{i}" for i in range(28, 50)] + [f"LP2/{i}" for i in range(51, 56)])
SEEDS = dict(gate_positive=33011511, gate_negative=33011512,
             multiset=33011511, global_bijection=33011512)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf8")


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


def digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def check_deadline(started: float) -> None:
    if time.monotonic() - started > WALL_SECONDS:
        raise TimeoutError("R015-A wall budget exceeded")


def load_pages() -> list[dict]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    expected = [f"LP2/{i}" for i in range(56)]
    if [page["page"] for page in corpus["pages"]] != expected:
        raise ValueError("LP2 corpus page order changed")
    pages = []
    for page in corpus["pages"]:
        values = [RUNES.index(char) for char in page["raw"] if char in RUNES]
        pages.append(dict(page=page["page"], raw=page["raw"], values=values,
                          rune_count=len(values), raw_sha256=page["raw_sha256"],
                          source=page["source"], source_sha256=page["source_sha256"],
                          image_path=page["image_path"]))
    if [page["page"] for page in pages if not page["values"]] != ["LP2/50"]:
        raise ValueError("LP2 applicability changed")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("LP2 rune count changed")
    return pages


def page_map(pages: list[dict]) -> dict[str, dict]:
    return {page["page"]: page for page in pages if page["values"]}


def public_page(page_id: str, values: list[int]) -> dict:
    return dict(page=page_id, cipher=list(values))


def model_public(model: dict) -> dict:
    return dict(start_weights=model["start_weights"],
                transition_weights=model["transition_weights"])


def op_value(value: int, operator: str) -> int:
    if operator == "A":
        return (-value + 2) % 29
    if operator == "S3":
        return (value + 3) % 29
    raise ValueError(f"not a stateless operator: {operator}")


def independent_primes(count: int) -> list[int]:
    result = []
    candidate = 2
    while len(result) < count:
        if all(candidate % p for p in result if p * p <= candidate):
            result.append(candidate)
        candidate += 1
    return result


def logadd(left: float, right: float) -> float:
    if left == float("-inf"):
        return right
    if right == float("-inf"):
        return left
    if left < right:
        left, right = right, left
    return left + math.log1p(math.exp(right - left))


def independent_score(values: list[int], recipe: tuple[str, ...], model: dict) -> float:
    """Second implementation of the DSL score, deliberately not imported."""
    if not values:
        return float("-inf")
    states = [i for i, operator in enumerate(recipe) if operator in STATE_OPERATORS]
    if not states:
        decoded = list(values)
        for operator in recipe:
            decoded = [op_value(value, operator) for value in decoded]
        total = model["start_weights"][decoded[0]]
        for left, right in zip(decoded, decoded[1:]):
            total += model["transition_weights"][left][right]
        return total / len(decoded)
    if len(states) != 1:
        raise ValueError("DSL state operator count changed")
    state_at = states[0]
    before = recipe[:state_at]
    after = recipe[state_at + 1:]
    state_operator = recipe[state_at]
    transformed = list(values)
    for operator in before:
        transformed = [op_value(value, operator) for value in transformed]
    prime_values = independent_primes(len(values)) if state_operator == "PRIME_MINUS_ONE" else None

    def delta(clock: int) -> int:
        return (DIVINITY[clock % len(DIVINITY)] if state_operator == "DIVINITY"
                else prime_values[clock] - 1)

    paths = {(0, None): (0.0, 1)}
    for position, ciphertext in enumerate(transformed):
        next_paths = {}
        for (clock, previous), (mass, count) in paths.items():
            options = []
            if ciphertext == 0:
                options.append((0, clock))
            normal = (ciphertext - delta(clock)) % 29
            if normal != 0:
                options.append((normal, clock + 1))
            for value, next_clock in options:
                output = value
                for operator in after:
                    output = op_value(output, operator)
                emission = (model["start_weights"][output] if previous is None
                            else model["transition_weights"][previous][output])
                key = (next_clock, output)
                old_mass, old_count = next_paths.get(key, (float("-inf"), 0))
                next_paths[key] = (logadd(old_mass, mass + emission), old_count + count)
        paths = next_paths
        if not paths:
            return float("-inf")
    total = float("-inf")
    for mass, _ in paths.values():
        total = logadd(total, mass)
    return total / len(values)


def independent_rank(pages: list[dict], programs: list[tuple[str, ...]], model: dict) -> dict:
    rows = []
    page_scores = {tuple(program): [] for program in programs}
    for program in programs:
        scores = [independent_score(page["values"], program, model) for page in pages]
        page_scores[tuple(program)] = scores
        value = float("-inf") if any(score == float("-inf") for score in scores) else sum(scores) / len(scores)
        rows.append(dict(program=list(program), depth=len(program), score=value,
                        page_scores=scores))
    rows.sort(key=lambda row: (-row["score"], row["depth"], row["program"]))
    return dict(selected=rows[0], rankings=rows)


def run_worker(run: Path, name: str, public: dict, timeout: int = 600) -> dict:
    folder = run / "worker" / name
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "public.json", public)
    result = execute([sys.executable, "-I", "-S", "-X", "utf8", str(WORKER_PATH)],
                     cwd=ROOT, timeout=timeout, stdin=json.dumps(public, ensure_ascii=False))
    write_json(folder / "execution.json", result)
    (folder / "stdout.json").write_text(result["stdout"], encoding="utf8")
    (folder / "stderr.txt").write_text(result["stderr"], encoding="utf8")
    if result["status"] != "completed":
        raise TimeoutError(f"R015-A worker {name}: {result['status']}") if result["status"] == "timeout" else RuntimeError(f"R015-A worker {name} failed")
    output = json.loads(result["stdout"])
    if not output.get("read_guard_probe_passed"):
        raise RuntimeError(f"R015-A worker guard failed: {name}")
    return output


def heldout_values() -> list[int]:
    from lp_lab.synthetic import encode_text
    return encode_text(HELDOUT_PATH.read_text(encoding="utf8"))


def make_gate(programs: list[tuple[str, ...]], model: dict) -> tuple[list[dict], dict]:
    source = heldout_values()
    if len(source) < 300:
        raise ValueError("heldout synthetic source too short")
    lengths = [96, 128, 160, 192, 224]
    positives = []
    private = {}
    for i in range(20):
        length = lengths[i % len(lengths)]
        start = (i * 53) % (len(source) - length)
        plain = source[start:start + length]
        recipe = programs[(i * 7 + 3) % len(programs)]
        cipher = encrypt_recipe(plain, recipe)
        job_id = f"positive-{i:02d}"
        positives.append(dict(id=job_id, pages=[public_page(job_id, cipher)]))
        private[job_id] = dict(kind="positive", start=start, length=length,
                               plaintext=plain, recipe=list(recipe), cipher=cipher)
    negatives = []
    rng = random.Random(SEEDS["gate_negative"])
    for i in range(99):
        length = lengths[(i + 2) % len(lengths)]
        start = (i * 31 + 17) % (len(source) - length)
        base = source[start:start + length]
        if i < 33:
            cipher = [rng.randrange(29) for _ in range(length)]
            kind = "uniform"
        elif i < 66:
            cipher = list(base)
            rng.shuffle(cipher)
            kind = "within_permutation"
        else:
            permutation = list(range(29))
            rng.shuffle(permutation)
            cipher = apply_symbol_permutation(base, permutation)
            kind = "global_s29"
        job_id = f"negative-{i:02d}"
        negatives.append(dict(id=job_id, pages=[public_page(job_id, cipher)]))
        private[job_id] = dict(kind=kind, start=start, length=length, cipher=cipher)
    gate_jobs = positives + negatives
    def natural_score(values):
        total = model["start_weights"][values[0]]
        total += sum(model["transition_weights"][left][right]
                     for left, right in zip(values, values[1:]))
        return total / len(values)

    positive_scores = [natural_score(row["plaintext"])
                       for row in private.values() if row["kind"] == "positive"]
    threshold = min(positive_scores) - 0.25
    return gate_jobs, dict(private=private, threshold=threshold,
                           positive_count=20, negative_count=99)


def validate_gate(output: dict, gate_private: dict, programs: list[tuple[str, ...]], model: dict) -> dict:
    by_id = {row["id"]: row for row in output["results"]}
    expected = set(gate_private["private"])
    if set(by_id) != expected:
        raise ValueError("R015-A gate coverage mismatch")
    positives = []
    negatives = []
    for job_id, private in gate_private["private"].items():
        row = by_id[job_id]
        recipe = tuple(row["selected"]["program"])
        independent = independent_rank([dict(values=private["cipher"])], programs, model)
        if row["selected"]["program"] != independent["selected"]["program"] or not math.isclose(
                row["selected"]["score"], independent["selected"]["score"], rel_tol=1e-11, abs_tol=1e-11):
            raise ValueError(f"R015-A gate independent selection mismatch: {job_id}")
        if private["kind"] == "positive":
            exact = recipe == tuple(private["recipe"])
            score_ok = row["selected"]["score"] >= gate_private["threshold"]
            roundtrip = encrypt_recipe(private["plaintext"], tuple(private["recipe"])) == private["cipher"]
            positives.append(dict(id=job_id, expected=private["recipe"], selected=row["selected"]["program"],
                                  exact_program=exact, score=row["selected"]["score"], score_ok=score_ok,
                                  roundtrip=roundtrip, status="passed" if exact and score_ok and roundtrip else "negative"))
        else:
            accepted = row["selected"]["score"] >= gate_private["threshold"]
            negatives.append(dict(id=job_id, kind=private["kind"], selected=row["selected"]["program"],
                                  score=row["selected"]["score"], false_accept=accepted,
                                  status="negative" if not accepted else "control_collision"))
    positive_passes = sum(row["status"] == "passed" for row in positives)
    false_accepts = sum(row["false_accept"] for row in negatives)
    return dict(status="passed" if positive_passes >= 18 and false_accepts == 0 else "failed",
                threshold=gate_private["threshold"], positive_passes=positive_passes,
                positive_count=len(positives), negative_false_accepts=false_accepts,
                negative_count=len(negatives), positives=positives, negatives=negatives)


def make_control_pages(pages: list[dict], family: str, replicate: int) -> tuple[list[dict], str]:
    rng = random.Random(SEEDS[family] + replicate)
    result = []
    if family == "multiset":
        for page in pages:
            values = list(page["values"])
            rng.shuffle(values)
            result.append(dict(page=page["page"], values=values))
    elif family == "global_bijection":
        permutation = list(range(29))
        rng.shuffle(permutation)
        for page in pages:
            result.append(dict(page=page["page"], values=apply_symbol_permutation(page["values"], permutation)))
    else:
        raise ValueError(f"unknown R015-A control family {family}")
    return result, digest([page["values"] for page in result])


def holm(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    adjusted = [1.0] * len(values)
    running = 0.0
    for rank, (index, value) in enumerate(ordered):
        running = max(running, min(1.0, value * (len(values) - rank)))
        adjusted[index] = running
    return adjusted


def p_high(value: float, controls: list[float]) -> float:
    if value == float("-inf"):
        return 1.0
    return (1 + sum(control >= value - TIE_TOLERANCE for control in controls)) / (len(controls) + 1)


def page_statistics(observed: list[float], controls: list[list[float]]) -> dict:
    if not controls:
        return dict(raw_p=[], holm_p=[], max_t_p=[], z=[])
    means = []
    stds = []
    z = []
    control_z_rows = []
    for index, value in enumerate(observed):
        sample = [row[index] for row in controls]
        finite = [x for x in sample if x != float("-inf")]
        if value == float("-inf") or not finite:
            means.append(float("-inf")); stds.append(0.0); z.append(0.0)
            control_z_rows.append([0.0] * len(controls))
            continue
        mean = sum(finite) / len(finite)
        variance = sum((x - mean) ** 2 for x in finite) / len(finite)
        std = math.sqrt(variance)
        means.append(mean); stds.append(std)
        z.append((value - mean) / std if std > 0 else 0.0)
        control_z_rows.append([(x - mean) / std if std > 0 and x != float("-inf") else 0.0 for x in sample])
    raw = [p_high(value, [row[index] for row in controls]) for index, value in enumerate(observed)]
    holm_p = holm(raw)
    max_control = [max((row[index] for index in range(len(observed))), default=0.0)
                   for row in zip(*control_z_rows)] if control_z_rows else []
    max_p = [(1 + sum(max_value >= observed_z - 1e-12 for max_value in max_control)) /
             (len(max_control) + 1) for observed_z in z]
    return dict(raw_p=raw, holm_p=holm_p, max_t_p=max_p, z=z, means=means, stds=stds,
                control_max_z=max_control)


def archive_run(run: Path, snapshot: dict) -> dict:
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / name for name in snapshot["files"]]
    for directory in ("data", "sources", "hypotheses", "research"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    paths.extend(path for path in run.rglob("*") if path.is_file() and path != archive)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(set(paths)):
            bundle.write(path, path.relative_to(ROOT).as_posix())
    return dict(path=archive.relative_to(ROOT).as_posix(), sha256=sha256(archive),
                bytes=archive.stat().st_size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("R015-A run must be inside runs/")
    run.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc)
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis=HYPOTHESIS, attempt="auto-cycle R015-A",
                  status="running", started_at_utc=started_at.isoformat(),
                  python=sys.version, executable=sys.executable, platform=platform.platform(),
                  code_version=snapshot, unsolved_page_candidates=[], controls_completed=0)
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        for source in spec["sources"]:
            if "sha256" in source and sha256(ROOT / source["path"]) != source["sha256"]:
                raise ValueError(f"R015-A source hash changed: {source['path']}")
        pages = load_pages()
        applicable = [page for page in pages if page["values"]]
        lookup = page_map(pages)
        programs, program_metadata = enumerate_recipes()
        model = build_language_model(TRAIN_PATH.read_text(encoding="utf8"))
        gate_jobs, gate_private = make_gate(programs, model)
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH), corpus_sha256=sha256(CORPUS_PATH),
                      training_sha256=sha256(TRAIN_PATH), heldout_sha256=sha256(HELDOUT_PATH),
                      source_files_verified=source_count, code_version=snapshot,
                      page_order=[page["page"] for page in pages], applicable_pages=[page["page"] for page in applicable],
                      discovery=list(DISCOVERY), holdout=list(HOLDOUT), excluded=["LP2/50"],
                      rune_count=sum(page["rune_count"] for page in applicable),
                      programs=[list(program) for program in programs], program_metadata=program_metadata,
                      model=dict(training_word_count=model["training_word_count"], training_symbol_count=model["training_symbol_count"],
                                 start_counts=model["start_counts"], transition_counts=model["transition_counts"],
                                 digest=digest(model)),
                      model_public_digest=digest(model_public(model)),
                      gate_threshold=gate_private["threshold"], gate_seeds=SEEDS,
                      controls=dict(count=CONTROL_COUNT, families=["multiset", "global_bijection"],
                                    seeds={"multiset": SEEDS["multiset"], "global_bijection": SEEDS["global_bijection"]}),
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE, wall_seconds=WALL_SECONDS)
        write_json(run / "frozen.json", frozen)
        write_json(run / "verifier-only" / "gate-answers.json", gate_private)
        gate_public = dict(schema=1, hypothesis=HYPOTHESIS,
                           programs=[list(program) for program in programs],
                           model=model_public(model), jobs=gate_jobs)
        gate_output = run_worker(run, "gate", gate_public)
        gate = validate_gate(gate_output, gate_private, programs, model)
        write_json(run / "gate.json", gate)
        record.update(source_files_verified=source_count, frozen_sha256=sha256(run / "frozen.json"),
                      gate_status=gate["status"], gate_positive_passes=gate["positive_passes"],
                      gate_negative_false_accepts=gate["negative_false_accepts"])
        write_json(run / "record.json", record)
        if gate["status"] != "passed":
            record.update(status="inconclusive", reason="power_gate_failed", finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          elapsed_seconds=time.monotonic() - started,
                          reproduction_bundle=archive_run(run, snapshot))
            write_json(run / "record.json", record)
            print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"],
                              "gate": gate["status"]}, ensure_ascii=False))
            return 0

        discovery_pages = [dict(page=page["page"], values=page["values"]) for page in applicable if page["page"] in DISCOVERY]
        holdout_pages = [dict(page=page["page"], values=page["values"]) for page in applicable if page["page"] in HOLDOUT]
        observed_rank_d = independent_rank(discovery_pages, programs, model)
        selected_recipe = tuple(observed_rank_d["selected"]["program"])
        observed_h_scores = [independent_score(page["values"], selected_recipe, model) for page in holdout_pages]
        public_formal = dict(schema=1, hypothesis=HYPOTHESIS,
                             programs=[list(program) for program in programs], model=model_public(model),
                             jobs=[dict(id="discovery", pages=[public_page(p["page"], p["values"]) for p in discovery_pages]),
                                   dict(id="holdout-selected", pages=[public_page(p["page"], p["values"]) for p in holdout_pages])])
        formal_output = run_worker(run, "formal-observed", public_formal, timeout=900)
        output_by_id = {row["id"]: row for row in formal_output["results"]}
        for name, expected_rank in (("discovery", observed_rank_d),):
            actual = output_by_id[name]["selected"]
            if actual["program"] != expected_rank["selected"]["program"] or not math.isclose(actual["score"], expected_rank["selected"]["score"], rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError("R015-A worker/independent discovery choice mismatch")
        holdout_row = next(item for item in output_by_id["holdout-selected"]["rankings"]
                          if tuple(item["program"]) == selected_recipe)
        for actual, expected in zip(holdout_row["page_scores"], observed_h_scores):
            if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError("R015-A worker/independent holdout score mismatch")
        write_json(run / "observed.json", dict(discovery=observed_rank_d["selected"],
                                                holdout_program=list(selected_recipe), holdout_scores=observed_h_scores,
                                                holdout_pages=[p["page"] for p in holdout_pages]))

        control_results = {"multiset": [], "global_bijection": []}
        control_page_scores = {"multiset": [], "global_bijection": []}
        for family in ("multiset", "global_bijection"):
            for replicate in range(CONTROL_COUNT):
                check_deadline(started)
                controlled, control_digest = make_control_pages(applicable, family, replicate)
                controlled_d = [page for page in controlled if page["page"] in DISCOVERY]
                controlled_h = [page for page in controlled if page["page"] in HOLDOUT]
                selected = independent_rank(controlled_d, programs, model)["selected"]
                program = tuple(selected["program"])
                h_scores = [independent_score(page["values"], program, model) for page in controlled_h]
                row = dict(replicate=replicate, family=family, input_sha256=control_digest,
                           selected_program=list(program), discovery_score=selected["score"],
                           holdout_scores=h_scores, holdout_score=(float("-inf") if any(x == float("-inf") for x in h_scores) else sum(h_scores) / len(h_scores)))
                control_results[family].append(row)
                control_page_scores[family].append(h_scores)
                if (replicate + 1) % 25 == 0:
                    write_json(run / "control-results.partial.json", control_results)
        write_json(run / "control-results.json", control_results)
        record["controls_completed"] = CONTROL_COUNT * 2
        write_json(run / "record.json", record)

        statistics = {"status": "negative", "verification_status": "passed",
                      "discovery": dict(selected_program=list(selected_recipe), observed_score=observed_rank_d["selected"]["score"]),
                      "holdout": dict(observed_scores=observed_h_scores, pages=[p["page"] for p in holdout_pages]),
                      "families": {}, "leads": [], "unsolved_page_candidates": [],
                      "negative_scope": "Only H029's 49 source-backed grammar programs, one state atom, page-local state-zero contract and two declared control families.",
                      "coverage": dict(pages=55, runes=12956, discovery_pages=len(discovery_pages), holdout_pages=len(holdout_pages),
                                       programs=len(programs), controls_per_family=CONTROL_COUNT)}
        discovery_controls = {family: [row["discovery_score"] for row in control_results[family]] for family in control_results}
        for family in control_results:
            control_h = control_page_scores[family]
            d_p = p_high(observed_rank_d["selected"]["score"], discovery_controls[family])
            h_mean = (float("-inf") if any(x == float("-inf") for x in observed_h_scores)
                      else sum(observed_h_scores) / len(observed_h_scores))
            h_controls = [row["holdout_score"] for row in control_results[family]]
            h_p = p_high(h_mean, h_controls)
            ps = page_statistics(observed_h_scores, control_h)
            family_leads = [dict(page=page["page"], raw_p=raw, holm_p=holm_p, max_t_p=max_p,
                                 score=score, status="lead" if holm_p <= ALPHA and max_p <= ALPHA else "negative")
                            for page, score, raw, holm_p, max_p in zip(holdout_pages, observed_h_scores,
                                                                        ps["raw_p"], ps["holm_p"], ps["max_t_p"])]
            statistics["families"][family] = dict(discovery_p=d_p, holdout_p=h_p,
                                                   page_statistics=family_leads,
                                                   max_t=ps, controls_completed=len(control_results[family]))
        # A formal lead requires the same at-least-two holdout pages under both
        # null families.  No text is emitted as a solution by this runner.
        common = set()
        for family in statistics["families"].values():
            common.update(row["page"] for row in family["page_statistics"]
                          if row["status"] == "lead")
        if all(statistics["families"][family]["discovery_p"] <= ALPHA and
               statistics["families"][family]["holdout_p"] <= ALPHA for family in statistics["families"]):
            # Require intersection rather than union; the same page must
            # survive both controls.
            page_sets = [set(row["page"] for row in statistics["families"][family]["page_statistics"] if row["status"] == "lead")
                         for family in statistics["families"]]
            common = set.intersection(*page_sets) if page_sets else set()
            if len(common) >= 2:
                statistics["status"] = "inconclusive"
                statistics["leads"] = sorted(common)
        write_json(run / "statistics.json", statistics)
        record.update(status=statistics["status"], result=dict(selected_program=list(selected_recipe),
                      leads=statistics["leads"], controls_completed=CONTROL_COUNT * 2),
                      actual_coverage=statistics["coverage"])
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("code changed during R015-A run")
        record["reproduction_bundle"] = archive_run(run, snapshot)
        record["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc),
                      finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      elapsed_seconds=time.monotonic() - started)
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
    write_json(run / "record.json", record)
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"],
                      "controls_completed": record.get("controls_completed", 0),
                      "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
