"""R015-B: F29 Berlekamp--Massey complexity and untouched-tail prediction."""

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


SPEC_PATH = ROOT / "hypotheses/H030-berlekamp-massey-v2.json"
CORPUS_PATH = ROOT / "data/attempt1-corpus-v1.json"
WORKER_PATH = ROOT / "scripts/attempt21_bm_v2_worker.py"
HYPOTHESIS = "H030-berlekamp-massey-v2"
VIEW_NAMES = ("raw", "difference", "position_prime_residual", "position_totient_residual")
MODULUS = 29
MIN_LENGTH = 96
MAX_ORDER = 16
CONTROL_COUNT = 999
ALPHA = 0.01 / 3.0
TIE_TOLERANCE = 1e-12
WALL_SECONDS = 3600
DISCOVERY = tuple(f"LP2/{i}" for i in range(28))
HOLDOUT = tuple([f"LP2/{i}" for i in range(28, 50)] + [f"LP2/{i}" for i in range(51, 56)])
CONTROL_SEED = 33011521


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
        raise TimeoutError("R015-B wall budget exceeded")


def load_pages() -> list[dict]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf8"))
    if [page["page"] for page in corpus["pages"]] != [f"LP2/{i}" for i in range(56)]:
        raise ValueError("LP2 page order changed")
    pages = []
    for page in corpus["pages"]:
        values = [RUNES.index(char) for char in page["raw"] if char in RUNES]
        pages.append(dict(page=page["page"], raw=page["raw"], values=values,
                          rune_count=len(values), raw_sha256=page["raw_sha256"],
                          source=page["source"], source_sha256=page["source_sha256"]))
    if [page["page"] for page in pages if not page["values"]] != ["LP2/50"]:
        raise ValueError("LP2 applicability changed")
    if sum(page["rune_count"] for page in pages) != 12956:
        raise ValueError("LP2 rune count changed")
    return pages


def independent_primes(count: int) -> list[int]:
    result = []
    candidate = 2
    while len(result) < count:
        if all(candidate % divisor for divisor in result if divisor * divisor <= candidate):
            result.append(candidate)
        candidate += 1
    return result


def independent_bm(sequence: list[int]) -> dict:
    if any(type(value) is not int or not 0 <= value < MODULUS for value in sequence):
        raise ValueError("BM sequence outside F29")
    connection = [1]
    backup = [1]
    order = 0
    shift = 1
    last = 1
    for n, value in enumerate(sequence):
        discrepancy = value
        for j in range(1, order + 1):
            discrepancy = (discrepancy + connection[j] * sequence[n - j]) % MODULUS
        if discrepancy == 0:
            shift += 1
            continue
        previous = connection[:]
        scale = discrepancy * pow(last, MODULUS - 2, MODULUS) % MODULUS
        if len(connection) < len(backup) + shift:
            connection.extend([0] * (len(backup) + shift - len(connection)))
        for j, coefficient in enumerate(backup):
            connection[j + shift] = (connection[j + shift] - scale * coefficient) % MODULUS
        if 2 * order <= n:
            order = n + 1 - order
            backup = previous
            last = discrepancy
            shift = 1
        else:
            shift += 1
    return dict(order=order, connection=connection[:order + 1])


def recurrence_holds(sequence: list[int], connection: list[int]) -> bool:
    order = len(connection) - 1
    return bool(connection) and connection[0] % MODULUS == 1 and all(
        sum(connection[j] * sequence[index - j] for j in range(order + 1)) % MODULUS == 0
        for index in range(order, len(sequence)))


def independent_predict(prefix: list[int], suffix_length: int, connection: list[int]) -> list[int]:
    order = len(connection) - 1
    values = list(prefix)
    for _ in range(suffix_length):
        values.append((-sum(connection[j] * values[-j] for j in range(1, order + 1))) % MODULUS)
    return values[len(prefix):]


def independent_views(cipher: list[int]) -> dict[str, list[int]]:
    primes = independent_primes(len(cipher))
    return {
        "raw": list(cipher),
        "difference": [(right - left) % MODULUS for left, right in zip(cipher, cipher[1:])],
        "position_prime_residual": [(value - primes[i]) % MODULUS for i, value in enumerate(cipher)],
        "position_totient_residual": [(value - (primes[i] - 1)) % MODULUS for i, value in enumerate(cipher)],
    }


def independent_metrics(sequence: list[int]) -> dict:
    n = len(sequence)
    full = independent_bm(sequence)
    if n < MIN_LENGTH:
        return dict(status="inconclusive_short", length=n, order=full["order"],
                    connection=full["connection"], prefix_length=None, suffix_length=None,
                    max_order=None, predicted_hits=None, prediction_rate=None,
                    t_l=None, t_p=None, full_order=full["order"], predicted_suffix=[],
                    recurrence_holds=recurrence_holds(sequence, full["connection"]))
    prefix_length = (2 * n) // 3
    suffix_length = n - prefix_length
    max_order = min(MAX_ORDER, prefix_length // 4)
    prefix = sequence[:prefix_length]
    fitted = independent_bm(prefix)
    order = fitted["order"]
    if order <= max_order:
        predicted = independent_predict(prefix, suffix_length, fitted["connection"])
        actual = sequence[prefix_length:]
        hits = sum(left == right for left, right in zip(predicted, actual))
    else:
        predicted = []
        hits = 0
    rate = hits / suffix_length
    recurrence_ok = recurrence_holds(prefix, fitted["connection"])
    return dict(status="eligible", length=n, prefix_length=prefix_length,
                suffix_length=suffix_length, max_order=max_order, order=order,
                register_length=order, connection=fitted["connection"],
                predicted_suffix=predicted, predicted_hits=hits,
                prediction_rate=rate, t_l=1.0 - 2.0 * order / prefix_length,
                t_p=rate, full_order=full["order"], recurrence_holds=recurrence_ok)


def all_metrics(values: list[int]) -> dict:
    return {name: independent_metrics(sequence) for name, sequence in independent_views(values).items()}


def run_worker(run: Path, name: str, jobs: list[dict], timeout: int = 600) -> dict:
    folder = run / "worker" / name
    folder.mkdir(parents=True, exist_ok=True)
    public = dict(schema=1, hypothesis=HYPOTHESIS, jobs=jobs)
    write_json(folder / "public.json", public)
    result = execute([sys.executable, "-I", "-S", "-X", "utf8", str(WORKER_PATH)],
                     cwd=ROOT, timeout=timeout, stdin=json.dumps(public, ensure_ascii=False))
    write_json(folder / "execution.json", result)
    (folder / "stdout.json").write_text(result["stdout"], encoding="utf8")
    (folder / "stderr.txt").write_text(result["stderr"], encoding="utf8")
    if result["status"] != "completed":
        if result["status"] == "timeout":
            raise TimeoutError(f"R015-B worker {name} timed out")
        raise RuntimeError(f"R015-B worker {name} failed")
    output = json.loads(result["stdout"])
    if not output.get("read_guard_probe_passed"):
        raise RuntimeError(f"R015-B worker read guard failed: {name}")
    return output


def make_recurrence(length: int, order: int, rng: random.Random) -> list[int]:
    coefficients = [rng.randrange(29) for _ in range(order)]
    coefficients[-1] = rng.randrange(1, 29)
    values = [rng.randrange(29) for _ in range(order)]
    for _ in range(order, length):
        values.append((-sum(coefficients[j - 1] * values[-j]
                             for j in range(1, order + 1))) % 29)
    return values


def make_gate() -> tuple[list[dict], dict]:
    lengths = [96, 128, 160, 192, 224]
    rng = random.Random(CONTROL_SEED)
    jobs = []
    private = {}
    for i in range(20):
        length = lengths[i % len(lengths)]
        order = (1, 2, 4, 8, 16)[i % 5]
        values = make_recurrence(length, order, rng)
        job_id = f"positive-{i:02d}"
        jobs.append(dict(id=job_id, cipher=values))
        private[job_id] = dict(kind="positive", order=order, cipher=values)
    for i in range(99):
        length = lengths[(i + 1) % len(lengths)]
        if i < 33:
            values = [rng.randrange(29) for _ in range(length)]
            kind = "uniform"
        elif i < 66:
            values = [rng.choices(range(7), weights=[7, 5, 4, 3, 2, 2, 1])[0]
                      for _ in range(length)]
            kind = "frequency_biased"
        else:
            order = (1, 2, 4, 8)[i % 4]
            prefix_length = (2 * length) // 3
            values = make_recurrence(prefix_length, order, rng)
            values.extend(rng.randrange(29) for _ in range(length - prefix_length))
            kind = "changed_tail"
        job_id = f"negative-{i:02d}"
        jobs.append(dict(id=job_id, cipher=values))
        private[job_id] = dict(kind=kind, cipher=values)
    return jobs, private


def validate_gate(output: dict, private: dict) -> dict:
    rows = {row["id"]: row for row in output["results"]}
    if set(rows) != set(private):
        raise ValueError("R015-B gate coverage mismatch")
    positives = []
    negatives = []
    for job_id, expected in private.items():
        raw = rows[job_id]["views"]["raw"]
        independent = independent_metrics(expected["cipher"])
        for key in ("status", "order", "connection", "prefix_length", "suffix_length", "max_order",
                    "predicted_hits", "t_l", "t_p", "recurrence_holds"):
            if raw.get(key) != independent.get(key):
                raise ValueError(f"R015-B gate independent mismatch {job_id}:{key}")
        accepted = raw["status"] == "eligible" and raw["order"] <= raw["max_order"] and raw["predicted_hits"] == raw["suffix_length"]
        if expected["kind"] == "positive":
            positives.append(dict(id=job_id, expected_order=expected["order"],
                                  observed_order=raw["order"], accepted=accepted,
                                  status="passed" if accepted else "negative"))
        else:
            negatives.append(dict(id=job_id, kind=expected["kind"], accepted=accepted,
                                  status="control_collision" if accepted else "negative"))
    positive_passes = sum(row["status"] == "passed" for row in positives)
    false_accepts = sum(row["accepted"] for row in negatives)
    return dict(status="passed" if positive_passes >= 18 and false_accepts == 0 else "failed",
                positive_passes=positive_passes, positive_count=len(positives),
                negative_false_accepts=false_accepts, negative_count=len(negatives),
                positives=positives, negatives=negatives)


def validate_observed(output: dict, pages: list[dict]) -> dict:
    expected_pages = {page["page"]: page for page in pages}
    observed = {row["id"]: row for row in output["results"]}
    if set(observed) != set(expected_pages):
        raise ValueError("R015-B observed page coverage mismatch")
    checks = 0
    normalized = {}
    for page_id, row in observed.items():
        expected = all_metrics(expected_pages[page_id]["values"])
        for name in VIEW_NAMES:
            actual = row["views"][name]
            reference = expected[name]
            for key in ("status", "length", "prefix_length", "suffix_length", "max_order", "order",
                        "connection", "predicted_hits", "prediction_rate", "t_l", "t_p", "full_order",
                        "recurrence_holds"):
                left, right = actual.get(key), reference.get(key)
                if isinstance(left, float) or isinstance(right, float):
                    if left is None or right is None or not math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-11):
                        raise ValueError(f"R015-B observed mismatch {page_id}:{name}:{key}")
                elif left != right:
                    raise ValueError(f"R015-B observed mismatch {page_id}:{name}:{key}")
            if actual.get("predicted_suffix") != reference.get("predicted_suffix"):
                raise ValueError(f"R015-B prediction mismatch {page_id}:{name}")
            checks += reference["length"]
        normalized[page_id] = expected
    return dict(status="passed", page_checks=len(pages), view_checks=len(pages) * len(VIEW_NAMES),
                rune_view_checks=checks, metrics=normalized)


def make_control_values(pages: list[dict], replicate: int) -> tuple[list[dict], str]:
    rng = random.Random(CONTROL_SEED + replicate)
    result = []
    for page in pages:
        values = list(page["values"])
        rng.shuffle(values)
        result.append(dict(page=page["page"], values=values))
    return result, digest([page["values"] for page in result])


def compact_metrics(metrics: dict) -> dict:
    return {name: dict(status=row["status"], length=row["length"], order=row["order"],
                       max_order=row.get("max_order"), predicted_hits=row.get("predicted_hits"),
                       suffix_length=row.get("suffix_length"), t_l=row.get("t_l"), t_p=row.get("t_p"),
                       full_order=row.get("full_order"), recurrence_holds=row.get("recurrence_holds"))
                for name, row in metrics.items()}


def p_high(value: float, controls: list[float]) -> float:
    return (1 + sum(control >= value - TIE_TOLERANCE for control in controls)) / (len(controls) + 1)


def statistic_rows(observed: dict, controls: list[dict], pages: list[dict], key: str) -> list[dict]:
    eligible = [(page["page"], name) for page in pages if page["page"] != "LP2/50"
                for name in VIEW_NAMES if observed[page["page"]][name]["status"] == "eligible"]
    by_cell = {}
    for page_id, name in eligible:
        values = [row[page_id][name][key] for row in controls]
        obs = observed[page_id][name][key]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        std = math.sqrt(variance)
        if std > 0:
            z = (obs - mean) / std
        elif obs > mean:
            z = float("inf")
        elif obs < mean:
            z = float("-inf")
        else:
            z = 0.0
        by_cell[(page_id, name)] = dict(page=page_id, view=name, observed=obs,
                                        control_mean=mean, control_std=std, z=z,
                                        raw_p=p_high(obs, values), partition=("discovery" if page_id in DISCOVERY else "holdout"))
    global_max = [max((by_cell[(page_id, name)]["z"] for page_id, name in eligible), default=0.0)
                  for _ in range(len(controls))]
    # Recompute the per-control maxima from raw values with the same cell means.
    global_max = []
    for replicate in range(len(controls)):
        control_values = []
        for page_id, name in eligible:
            cell = by_cell[(page_id, name)]
            value = ((controls[replicate][page_id][name][key] - cell["control_mean"]) /
                     cell["control_std"] if cell["control_std"] > 0 else 0.0)
            control_values.append(value)
        global_max.append(max(control_values, default=0.0))
    rows = []
    for cell in by_cell.values():
        cell = dict(cell)
        cell["max_t_p"] = (1 + sum(value >= cell["z"] - TIE_TOLERANCE for value in global_max)) / (len(global_max) + 1)
        rows.append(cell)
    return sorted(rows, key=lambda row: (row["max_t_p"], row["page"], row["view"]))


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
        raise ValueError("R015-B run must be inside runs/")
    run.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    started_at = dt.datetime.now(dt.timezone.utc)
    snapshot = code_snapshot(ROOT)
    record = dict(schema=1, hypothesis=HYPOTHESIS, attempt="auto-cycle R015-B", status="running",
                  started_at_utc=started_at.isoformat(), python=sys.version, executable=sys.executable,
                  platform=platform.platform(), code_version=snapshot, controls_completed=0,
                  unsolved_page_candidates=[])
    write_json(run / "record.json", record)
    try:
        source_count = verify_sources(ROOT)
        spec = json.loads(SPEC_PATH.read_text(encoding="utf8"))
        for source in spec["sources"]:
            if "sha256" in source and sha256(ROOT / source["path"]) != source["sha256"]:
                raise ValueError(f"R015-B source hash changed: {source['path']}")
        pages = load_pages()
        applicable = [page for page in pages if page["values"]]
        gate_jobs, gate_private = make_gate()
        frozen = dict(schema=1, frozen_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      specification_sha256=sha256(SPEC_PATH), corpus_sha256=sha256(CORPUS_PATH),
                      source_files_verified=source_count, code_version=snapshot,
                      page_order=[page["page"] for page in pages], discovery=list(DISCOVERY), holdout=list(HOLDOUT),
                      excluded=["LP2/50"], views=list(VIEW_NAMES), field="F29", minimum_length=MIN_LENGTH,
                      prefix_rule="floor(2N/3)", max_order_rule="min(16,floor(prefix_length/4))",
                      controls=dict(count=CONTROL_COUNT, seed=CONTROL_SEED, null="within-page permutation before six views"),
                      alpha=ALPHA, tie_tolerance=TIE_TOLERANCE, wall_seconds=WALL_SECONDS,
                      rune_count=sum(page["rune_count"] for page in applicable),
                      gate=dict(positive_count=20, negative_count=99, seed=CONTROL_SEED))
        write_json(run / "frozen.json", frozen)
        write_json(run / "verifier-only" / "gate-answers.json", gate_private)
        gate_output = run_worker(run, "gate", gate_jobs)
        gate = validate_gate(gate_output, gate_private)
        write_json(run / "gate.json", gate)
        record.update(source_files_verified=source_count, frozen_sha256=sha256(run / "frozen.json"),
                      gate_status=gate["status"], gate_positive_passes=gate["positive_passes"],
                      gate_negative_false_accepts=gate["negative_false_accepts"])
        write_json(run / "record.json", record)
        if gate["status"] != "passed":
            record.update(status="inconclusive", reason="power_gate_failed",
                          finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                          elapsed_seconds=time.monotonic() - started,
                          reproduction_bundle=archive_run(run, snapshot))
            write_json(run / "record.json", record)
            print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"], "gate": gate["status"]}, ensure_ascii=False))
            return 0
        observed_output = run_worker(run, "formal-observed", [dict(id=page["page"], cipher=page["values"]) for page in applicable], timeout=900)
        verification = validate_observed(observed_output, applicable)
        write_json(run / "independent-verification.json", {key: value for key, value in verification.items() if key != "metrics"})
        observed_metrics = verification["metrics"]
        write_json(run / "observed.json", dict(pages=observed_metrics, page_order=[page["page"] for page in applicable]))
        controls = []
        for replicate in range(CONTROL_COUNT):
            check_deadline(started)
            controlled, control_digest = make_control_values(applicable, replicate)
            row = {page["page"]: compact_metrics(all_metrics(page["values"])) for page in controlled}
            controls.append(dict(replicate=replicate, input_sha256=control_digest, pages=row))
            if (replicate + 1) % 25 == 0:
                write_json(run / "control-results.partial.json", controls)
        write_json(run / "control-results.json", controls)
        record["controls_completed"] = CONTROL_COUNT
        write_json(run / "record.json", record)
        # Compact control lookup for statistics, avoiding any dependence on
        # the worker's JSON representation.
        control_lookup = [{page_id: {name: row["pages"][page_id][name] for name in VIEW_NAMES}
                           for page_id in row["pages"]} for row in controls]
        stats_l = statistic_rows(observed_metrics, control_lookup, applicable, "t_l")
        stats_p = statistic_rows(observed_metrics, control_lookup, applicable, "t_p")
        l_map = {(row["page"], row["view"]): row for row in stats_l}
        p_map = {(row["page"], row["view"]): row for row in stats_p}
        leads = []
        for key, l_row in l_map.items():
            p_row = p_map[key]
            observed_row = observed_metrics[key[0]][key[1]]
            full_suffix = (observed_row["status"] == "eligible" and
                           observed_row["order"] <= observed_row["max_order"] and
                           observed_row["predicted_hits"] == observed_row["suffix_length"])
            if (key[0] in HOLDOUT and full_suffix and
                    l_row["max_t_p"] <= ALPHA and p_row["max_t_p"] <= ALPHA):
                leads.append(dict(page=key[0], view=key[1], t_l=l_row, t_p=p_row))
        strongest = sorted((dict(page=key[0], view=key[1], t_l=l_map[key], t_p=p_map[key])
                            for key in l_map), key=lambda row: (row["t_l"]["max_t_p"], row["t_p"]["max_t_p"], row["page"], row["view"]))[:20]
        summary = dict(status="inconclusive" if leads else "negative", verification_status="passed",
                       controls_completed=CONTROL_COUNT, leads=leads, strongest=strongest,
                       statistics=dict(T_L=stats_l, T_P=stats_p),
                       coverage=dict(pages=55, applicable_pages=55, excluded_pages=["LP2/50"],
                                     runes=12956, view_count=len(VIEW_NAMES), eligible_cells=len(stats_l),
                                     controls=CONTROL_COUNT),
                       negative_scope="Only the six fixed representations, F29 BM protocol, page reset, prefix fraction, order cap and within-page permutation null.")
        write_json(run / "statistics.json", summary)
        record.update(status=summary["status"], result=dict(leads=leads, strongest=strongest[:3]), actual_coverage=summary["coverage"])
        if code_snapshot(ROOT) != snapshot:
            raise RuntimeError("code changed during R015-B run")
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
                      "controls_completed": record.get("controls_completed", 0), "error": record.get("error")}, ensure_ascii=False))
    return 0 if record["status"] in {"passed", "negative", "inconclusive"} else 1


if __name__ == "__main__":
    sys.exit(main())
