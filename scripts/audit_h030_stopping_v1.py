"""Audit H030's already-frozen necessary condition; do not extend its search.

Gaussian elimination at the cap is independent of BM: every order L <= cap
recurrence extends to a cap-order recurrence with zero trailing coefficients.
An inconsistent cap-order system therefore excludes every admitted order.
"""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import traceback
import zipfile

import attempt21_bm_v2 as base

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runs/auto-cycle-r015-H030-v3"
SPEC = ROOT / "hypotheses/H030-stopping-audit-v1.json"


def finite_field_rank(matrix):
    rows = [list(row) for row in matrix]
    if not rows:
        return 0
    pivot = 0
    for column in range(len(rows[0])):
        chosen = next((i for i in range(pivot, len(rows)) if rows[i][column] % 29), None)
        if chosen is None:
            continue
        rows[pivot], rows[chosen] = rows[chosen], rows[pivot]
        scale = pow(rows[pivot][column], -1, 29)
        rows[pivot] = [value * scale % 29 for value in rows[pivot]]
        for i in range(pivot + 1, len(rows)):
            factor = rows[i][column]
            if factor:
                rows[i] = [(a - factor * b) % 29 for a, b in zip(rows[i], rows[pivot])]
        pivot += 1
        if pivot == len(rows):
            break
    return pivot


def order_cap_oracle(sequence, cap):
    augmented = [[sequence[t - j] for j in range(1, cap + 1)] + [(-sequence[t]) % 29]
                 for t in range(cap, len(sequence))]
    a_rank = finite_field_rank([row[:-1] for row in augmented])
    ab_rank = finite_field_rank(augmented)
    return dict(method="F29 Gaussian rank consistency at fixed order cap",
                coefficient_rank=a_rank, augmented_rank=ab_rank,
                consistent=a_rank == ab_rank, equation_count=len(augmented), unknowns=cap)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run = args.out.resolve()
    if not run.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Audit output must be inside runs")
    run.mkdir(exist_ok=False)
    start = time.monotonic()
    record = dict(schema=1, hypothesis="H030-stopping-audit-v1", status="running",
                  scientific_status="inconclusive", source_run=SOURCE.relative_to(ROOT).as_posix(),
                  started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  controls_completed=575, new_formal_controls=0, unsolved_page_candidates=[])
    log = []
    exit_code = 0
    try:
        spec = json.loads(SPEC.read_text(encoding="utf8"))
        hashes = {item["path"]: base.sha256(ROOT / item["path"]) for item in spec["inputs"]}
        for item in spec["inputs"]:
            if hashes[item["path"]] != item["sha256"]:
                raise ValueError(f"Frozen input changed: {item['path']}")
        base.write_json(run / "frozen.json", dict(specification_sha256=base.sha256(SPEC),
                                                  inputs=hashes, user_stopping_policy=spec["user_stopping_policy"]))
        partial = json.loads((SOURCE / "control-results.partial.json").read_text(encoding="utf8"))
        checkpoint = json.loads((SOURCE / "control-checkpoint.json").read_text(encoding="utf8"))
        frozen = json.loads((SOURCE / "frozen.json").read_text(encoding="utf8"))
        if len(partial) != 575 or checkpoint["completed"] != 575 or checkpoint["next_replicate"] != 575:
            raise ValueError("Expected preserved 575-row safe checkpoint")
        if base.sha256(SOURCE / "control-results.partial.json") != checkpoint["partial_sha256"]:
            raise ValueError("Checkpoint partial hash mismatch")
        if base.sha256(SOURCE / "frozen.json") != checkpoint["frozen_sha256"]:
            raise ValueError("Checkpoint frozen hash mismatch")
        if frozen["corpus_sha256"] != base.sha256(base.CORPUS_PATH):
            raise ValueError("Corpus hash mismatch")
        for item in json.loads((ROOT / "hypotheses/H030-berlekamp-massey-v3.json").read_text(encoding="utf8"))["sources"]:
            if "sha256" in item and base.sha256(ROOT / item["path"]) != item["sha256"]:
                raise ValueError("Historical source hash mismatch")
        pages = [page for page in base.load_pages() if page["values"]]
        for i, row in enumerate(partial):
            if type(row["replicate"]) is not int or row["replicate"] != i:
                raise ValueError("Historical replicate IDs changed")
            _, digest = base.make_control_values(pages, i)
            if row["input_sha256"] != digest:
                raise ValueError(f"Historical random input changed at {i}")
        integrity = dict(status="passed", completed=575, next_replicate=575,
                         input_digest_replays=575, metric_rows_replayed=0,
                         scope="All historical bytes, IDs and input digests checked; compact BM metrics not rerun.")
        base.write_json(run / "source-integrity.json", integrity)
        log.append("Source integrity passed: 575 rows and all 575 deterministic input digests; no new controls accepted.")
        worker_output = json.loads((SOURCE / "worker/formal-observed/stdout.json").read_text(encoding="utf8"))
        verification = base.validate_observed(worker_output, pages)
        observed = json.loads((SOURCE / "observed.json").read_text(encoding="utf8"))
        if canonical(verification["metrics"]) != canonical(observed["pages"]):
            raise ValueError("Recomputed observed metrics differ from stored observed")
        rows = []
        for page in pages:
            for view, values in base.independent_views(page["values"]).items():
                metric = verification["metrics"][page["page"]][view]
                row = dict(page=page["page"], view=view, length=len(values), status=metric["status"],
                           partition="discovery" if page["page"] in base.DISCOVERY else "holdout",
                           order=metric["order"], cap=metric.get("max_order"),
                           predicted_hits=metric["predicted_hits"], suffix_length=metric["suffix_length"],
                           order_within_cap=None, rank_oracle=None)
                if metric["status"] == "eligible":
                    row["order_within_cap"] = metric["order"] <= metric["max_order"]
                    row["rank_oracle"] = order_cap_oracle(values[:metric["prefix_length"]], metric["max_order"])
                    if row["order_within_cap"] != row["rank_oracle"]["consistent"]:
                        raise ValueError(f"Independent order-cap contradiction: {page['page']}:{view}")
                rows.append(row)
        eligible = [row for row in rows if row["status"] == "eligible"]
        result = dict(status="inconclusive", audit_verification="passed", pages=len(pages),
                      runes=sum(page["rune_count"] for page in pages), view_cells=len(rows),
                      eligible_cells=len(eligible), short_cells=len(rows) - len(eligible),
                      discovery_eligible=sum(row["partition"] == "discovery" for row in eligible),
                      holdout_eligible=sum(row["partition"] == "holdout" for row in eligible),
                      minimum_fitted_order=min(row["order"] for row in eligible),
                      maximum_admitted_order=max(row["cap"] for row in eligible),
                      admitted_low_order_cells=sum(row["order_within_cap"] for row in eligible),
                      independent_inconsistent_cap_systems=sum(not row["rank_oracle"]["consistent"] for row in eligible),
                      excluded_pages=[dict(page="LP2/50", reason="No registered rune tokens")],
                      controls_completed=575, controls_requested=999, new_formal_controls=0,
                      leads=[], unsolved_page_candidates=[],
                      stopped_reason="Necessary low-order gate fails in every eligible observed cell; user requests immediate method switch when unpromising.",
                      non_conclusion="No completed maxT statistic or formal 999-control negative; no claim about hidden key recurrence, nonlinear mechanisms, alternate views or untested orders.")
        base.write_json(run / "coverage.json", dict(cells=rows, excluded_pages=result["excluded_pages"]))
        base.write_json(run / "independent-verification.json", {key: value for key, value in verification.items() if key != "metrics"})
        base.write_json(run / "result.json", result)
        if time.monotonic() - start > spec["wall_seconds"]:
            raise TimeoutError("Stopping audit exceeded frozen budget")
        for path, expected in hashes.items():
            if base.sha256(ROOT / path) != expected:
                raise ValueError(f"Audit input mutated: {path}")
        record.update(status="inconclusive", audit_verification="passed", result=result,
                      source_integrity=integrity, actual_coverage={k: result[k] for k in
                        ("pages", "runes", "view_cells", "eligible_cells", "short_cells", "controls_completed")})
        log.append(canonical(result))
    except Exception as exc:
        record.update(status="timeout" if isinstance(exc, TimeoutError) else "error", error=repr(exc))
        (run / "runner.stderr.txt").write_text(traceback.format_exc(), encoding="utf8")
        exit_code = 1
    record.update(finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  elapsed_seconds=time.monotonic() - start, exit_code=exit_code)
    (run / "runner.stdout.txt").write_text("\n".join(log) + "\n", encoding="utf8")
    if not (run / "runner.stderr.txt").exists():
        (run / "runner.stderr.txt").write_text("", encoding="utf8")
    base.write_json(run / "record.json", record)
    base.write_json(run / "execution.json", dict(command=[sys.executable, "-X", "utf8", str(Path(__file__)), "--out", str(run)],
                                                exit_code=exit_code, elapsed_seconds=record["elapsed_seconds"]))
    archive = run / "reproduction-bundle.zip"
    paths = [ROOT / item["path"] for item in json.loads(SPEC.read_text(encoding="utf8"))["inputs"]]
    paths += [SPEC] + [p for p in run.rglob("*") if p.is_file()]
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(paths)):
            z.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("Reproduction archive CRC failure")
    base.write_json(run / "reproduction-manifest.json", dict(path=archive.relative_to(ROOT).as_posix(),
                  sha256=base.sha256(archive), crc="passed", members=len(paths)))
    print(json.dumps({"run": run.relative_to(ROOT).as_posix(), "status": record["status"], "exit_code": exit_code}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
