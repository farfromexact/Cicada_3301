"""Frozen H006 conditional permutation statistics; no reference/answer inputs.

Each replicate independently shuffles the rune values within each page and
reuses that page permutation for every registered clock. The maximum covers
the entire deduplicated page-by-clock family. This tests the global
within-page exchangeability null, not whether a candidate is a decipherment.
"""
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import sys
import time


ZERO_RESIDUAL_ULPS = 64


def _validate_indices(values, name):
    if not values or any(type(v) is not int or not 0 <= v < 29 for v in values):
        raise ValueError(f"{name} must contain nonempty rune indices 0..28")


def _validate_weights(weights):
    if len(weights) != 29 or any(not math.isfinite(w) for w in weights):
        raise ValueError("Expected 29 finite frozen weights")


def permutation_moments(cipher, delta, weights):
    """Exact conditional mean/variance of a sum under uniform permutations.

For a_ij = w[(cipher_j-delta_i)%29], the mean is total(a)/n and
variance is (sum(a^2)-sum(row_sums^2)/n-sum(col_sums^2)/n
             +total(a)^2/n^2)/(n-1).
The equivalent doubly centered sum of squares below avoids cancellation;
the 29 by 29 histogram calculation includes repeated rune values exactly.
"""
    _validate_indices(cipher, "cipher")
    _validate_indices(delta, "delta")
    _validate_weights(weights)
    n = len(cipher)
    if len(delta) != n:
        raise ValueError("Cipher and delta lengths differ")
    cc, cd = Counter(cipher), Counter(delta)
    row_means = {d: math.fsum(count * weights[(c-d) % 29]
                              for c, count in cc.items()) / n for d in cd}
    col_means = {c: math.fsum(count * weights[(c-d) % 29]
                              for d, count in cd.items()) / n for c in cc}
    mean = math.fsum(count * row_means[d] for d, count in cd.items())
    if n == 1 or len(cc) == 1 or len(cd) == 1:
        return mean, 0.0
    grand_mean = mean / n
    residuals = [(cd[d] * cc[c], weights[(c-d) % 29]
                  - row_means[d] - col_means[c] + grand_mean)
                 for d in cd for c in cc]
    tolerance = ZERO_RESIDUAL_ULPS * sys.float_info.epsilon * max(1.0, max(map(abs, weights)))
    if max(abs(r) for _, r in residuals) <= tolerance:
        return mean, 0.0
    variance = math.fsum(count * residual * residual
                         for count, residual in residuals) / (n-1)
    return mean, variance


def _z(score, mean, variance):
    return (score-mean) / math.sqrt(variance) if variance > 0 else 0.0


def _digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf8")
    return hashlib.sha256(payload).hexdigest()


def analyze(pages, results, weights, out_dir, permutations=999, control_seed=33010601,
            timeout_seconds=180):
    """Write all control scores/maxima and return adjusted lead-only evidence.

Caller supplies a frozen, deduplicated candidate family. A single seeded RNG
is used only here in the control generator; no key or plaintext answer is
generated, read, or passed to a candidate search module.
"""
    started = time.monotonic()
    _validate_weights(weights)
    if type(permutations) is not int or permutations < 1:
        raise ValueError("At least one pre-registered control replicate is required")
    if type(control_seed) is not int:
        raise ValueError("Control seed must be an integer")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Timeout must be positive and finite")
    if not pages or not results:
        raise ValueError("Empty pages or candidate family")
    page_map = {}
    for page in pages:
        if page["page"] in page_map:
            raise ValueError("Duplicate page identifier")
        _validate_indices(page["cipher"], "cipher")
        page_map[page["page"]] = list(page["cipher"])

    moments, observed_scores, observed_z, keys = [], [], [], set()
    by_page = {page: [] for page in page_map}
    descriptors = []
    for index, result in enumerate(results):
        page, delta = result["page"], result["delta"]
        if page not in page_map:
            raise ValueError("Candidate page absent from input corpus")
        if not result["methods"] or any(not isinstance(m, str) for m in result["methods"]):
            raise ValueError("Candidate methods must be nonempty names")
        key = page, tuple(delta)
        if key in keys:
            raise ValueError("Candidate family must be deduplicated by page and full delta vector")
        keys.add(key)
        mean, variance = permutation_moments(page_map[page], delta, weights)
        plain = [(c-d) % 29 for c, d in zip(page_map[page], delta)]
        if plain != result["plaintext"]:
            raise ValueError("Candidate plaintext is inconsistent with cipher and delta")
        score = math.fsum(weights[c] for c in plain)
        supplied = result["log_likelihood"]
        if not math.isfinite(supplied) or not math.isclose(score, supplied, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Candidate likelihood differs from frozen weights")
        moments.append((mean, variance))
        observed_scores.append(score)
        observed_z.append(_z(score, mean, variance))
        by_page[page].append(index)
        descriptors.append(dict(index=index, page=page, methods=list(result["methods"]),
                                rune_count=len(plain), delta_sha256=_digest(delta),
                                null_mean=mean, null_variance=variance))
    if any(not indices for indices in by_page.values()):
        raise ValueError("A rune-containing input page has no candidate coverage")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    control_path = out_dir / "control-scores.json"
    if control_path.exists():
        raise FileExistsError("Control records are append-only; choose a fresh output directory")
    metadata = dict(schema=1, generated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    algorithm="exact conditional permutation moments and corpus-wide maximum z",
                    rng="Python random.Random, MT19937; shuffle per page reused across clocks",
                    python_version=platform.python_version(), control_seed=control_seed,
                    requested_control_replicates=permutations, completed_control_replicates=0,
                    timeout_seconds=timeout_seconds, unique_candidates=len(results), rune_pages=len(pages),
                    page_order=list(page_map), seed_scope="control generator only; never a candidate key",
                    zero_variance_rule="z=0 and adjusted p=1; constant residual tolerance is 64 binary64 eps times max(1, max_abs_weight)",
                    input_sha256=_digest(dict(pages=pages, results=results, weights=weights)),
                    weights_sha256=_digest(weights),
                    p_adjusted_rule="(1 + count(control family maximum z >= observed candidate z))/(B+1)",
                    family="all supplied page-by-clock candidates, deduplicated by full per-rune delta vector",
                    interpretation="Global within-page exchangeability null; significant unigram alignment is a lead, not decipherment; absence of a lead is limited to this scorer and family")
    def save_controls(status):
        metadata.update(status=status, completed_control_replicates=len(control_rows),
                        elapsed_seconds=time.monotonic()-started)
        artifact = dict(metadata=metadata, candidate_columns=descriptors,
                        observed=dict(log_likelihood=observed_scores, z=observed_z, max_z=max(observed_z)),
                        replicates=control_rows, max_z=maxima)
        with control_path.open("x", encoding="utf8") as stream:
            json.dump(artifact, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")

    rng = random.Random(control_seed)
    lookup = [[weights[(c-d) % 29] for c in range(29)] for d in range(29)]
    control_rows, maxima = [], []
    for replicate in range(1, permutations+1):
        if time.monotonic()-started >= timeout_seconds:
            save_controls("timeout")
            raise TimeoutError(f"Control timeout after {len(control_rows)}/{permutations} complete replicates; partial record: {control_path}")
        scores, zs = [None] * len(results), [None] * len(results)
        for page, original in page_map.items():
            shuffled = original.copy()
            rng.shuffle(shuffled)
            for index in by_page[page]:
                delta = results[index]["delta"]
                score = math.fsum(lookup[d][c] for c, d in zip(shuffled, delta))
                scores[index] = score
                zs[index] = _z(score, *moments[index])
        maximum = max(zs)
        maxima.append(maximum)
        control_rows.append(dict(replicate=replicate, log_likelihood=scores, z=zs, max_z=maximum))

    rows = []
    for index, result in enumerate(results):
        exceedances = sum(maximum >= observed_z[index] for maximum in maxima)
        p_adjusted = (1+exceedances) / (permutations+1)
        # A constant permutation score has no power and can never be a lead.
        if moments[index][1] == 0:
            p_adjusted = 1.0
        rows.append(dict(page=result["page"], methods=list(result["methods"]),
                         log_likelihood=observed_scores[index], z=observed_z[index],
                         null_mean=moments[index][0], null_variance=moments[index][1],
                         exceedances=exceedances, p_adjusted=p_adjusted,
                         status="inconclusive" if p_adjusted <= .01 else "negative"))
    save_controls("completed")
    return dict(metadata=metadata, rows=rows,
                lead_count=sum(row["status"] == "inconclusive" for row in rows),
                completed_control_replicates=len(control_rows),
                requested_control_replicates=permutations, unique_candidates=len(results),
                control_scores_path=str(control_path),
                control_scores_sha256=hashlib.sha256(control_path.read_bytes()).hexdigest())
