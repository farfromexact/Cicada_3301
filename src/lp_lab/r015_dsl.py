"""R015-A's closed, source-backed operation language.

This module contains only the public search algebra.  It deliberately does
not read corpus files, answers, seeds, or private keys.  The two stateful
atoms are inverse decoders for the two mechanisms reproduced on known pages;
their F exception is represented as a finite-state path sum rather than a
chosen plaintext path.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import defaultdict

from .runes import RUNES
from .synthetic import encode_text


MODULUS = 29
DIVINITY = (23, 10, 1, 10, 9, 10, 16, 26)
OPERATORS = ("A", "S3", "DIVINITY", "PRIME_MINUS_ONE")
STATE_OPERATORS = frozenset({"DIVINITY", "PRIME_MINUS_ONE"})
MAX_DEPTH = 3
PRIME_CACHE: list[int] = []


def primes(count: int) -> list[int]:
    if type(count) is not int or count < 0:
        raise ValueError("prime count must be a non-negative integer")
    candidate = PRIME_CACHE[-1] + 1 if PRIME_CACHE else 2
    while len(PRIME_CACHE) < count:
        if all(candidate % p for p in PRIME_CACHE if p * p <= candidate):
            PRIME_CACHE.append(candidate)
        candidate += 1
    return PRIME_CACHE[:count]


def _point_value(value: int, operator: str, position: int, *, inverse: bool = False) -> int:
    if operator == "A":
        return (-value + 2) % MODULUS
    if operator == "S3":
        return (value - 3 if inverse else value + 3) % MODULUS
    if operator in STATE_OPERATORS:
        if inverse:
            delta = (DIVINITY[position % len(DIVINITY)] if operator == "DIVINITY"
                     else primes(position + 1)[position] - 1)
            return (value + delta) % MODULUS
        raise ValueError("stateful operators require the path engine")
    raise ValueError(f"unknown operator {operator}")


def apply_stateless(values: list[int], operator: str, *, inverse: bool = False) -> list[int]:
    if operator not in {"A", "S3"}:
        raise ValueError("apply_stateless accepts only A or S3")
    if any(type(value) is not int or not 0 <= value < MODULUS for value in values):
        raise ValueError("rune values must be in 0..28")
    return [_point_value(value, operator, position, inverse=inverse)
            for position, value in enumerate(values)]


def apply_recipe(values: list[int], recipe: tuple[str, ...]) -> list[int]:
    """Apply a recipe to a single page-local rune stream.

    This deterministic helper is used for symbolic probes and inverse
    encryption.  A stateful recipe must be evaluated with ``score_recipe``;
    this function rejects it instead of silently selecting a path.
    """
    result = list(values)
    for operator in recipe:
        if operator in STATE_OPERATORS:
            raise ValueError("stateful recipe needs score_recipe or encrypt_recipe")
        result = apply_stateless(result, operator)
    return result


def encrypt_recipe(values: list[int], recipe: tuple[str, ...]) -> list[int]:
    """Independently defined forward map for synthetic gate positives."""
    result = list(values)
    for operator in reversed(recipe):
        if operator == "A":
            result = apply_stateless(result, "A")
        elif operator == "S3":
            result = apply_stateless(result, "S3", inverse=True)
        elif operator in STATE_OPERATORS:
            deltas = (DIVINITY if operator == "DIVINITY"
                      else [p - 1 for p in primes(len(result))])
            encrypted = []
            clock = 0
            for value in result:
                if value == 0:
                    encrypted.append(0)
                else:
                    delta = (deltas[clock % len(deltas)] if operator == "DIVINITY"
                             else deltas[clock])
                    encrypted.append((value + delta) % MODULUS)
                    clock += 1
            result = encrypted
        else:
            raise ValueError(f"unknown operator {operator}")
    return result


def enumerate_recipes(max_depth: int = MAX_DEPTH) -> tuple[list[tuple[str, ...]], dict]:
    """Return the 49 programs after grammar-level, source-independent dedup.

    The grammar is: depth 0..3 over four registered atoms, with at most one
    state atom.  No page data is used to deduplicate programs.  The fixed
    operator probe checks every input value at positions 0..1023, making the
    recorded equivalence a property of this finite DSL contract rather than
    an accidental equality on an LP2 page.
    """
    if max_depth < 0 or max_depth > MAX_DEPTH:
        raise ValueError("depth outside the preregistered range")
    raw = [()]
    for depth in range(1, max_depth + 1):
        raw.extend(tuple(items) for items in itertools.product(OPERATORS, repeat=depth)
                   if sum(item in STATE_OPERATORS for item in items) <= 1)
    groups: dict[tuple[int, ...], list[tuple[str, ...]]] = defaultdict(list)
    probe_positions = range(1024)
    for recipe in raw:
        # A is an involution.  Cancel only adjacent A atoms; this is a
        # symbol-level rewrite and remains valid when a state atom is absent
        # between them.  It does not use a page's observed output.
        canonical = []
        for operator in recipe:
            if operator == "A" and canonical and canonical[-1] == "A":
                canonical.pop()
            else:
                canonical.append(operator)
        canonical = tuple(canonical)
        if any(operator in STATE_OPERATORS for operator in canonical):
            # A state atom is a transducer with a path relation, not a plain
            # pointwise map.  Keep each of these grammar strings distinct;
            # no page-dependent or path-dependent equality is inferred.
            signature = ("stateful",) + canonical
        else:
            signature = []
            for position in probe_positions:
                for value in range(MODULUS):
                    current = value
                    for operator in canonical:
                        current = _point_value(current, operator, position)
                    signature.append(current)
            signature = tuple(signature)
        groups[signature].append(canonical)
    representatives = [min(group, key=lambda item: (len(item), item))
                       for group in groups.values()]
    representatives.sort(key=lambda item: (len(item), item))
    metadata = dict(raw_count=len(raw), unique_count=len(representatives),
                    probe_positions=1024, probe_values=29,
                    state_operator_limit=1,
                    raw_programs=[list(recipe) for recipe in raw],
                    equivalence_classes=[{
                        "representative": list(min(group, key=lambda item: (len(item), item))),
                        "members": [list(item) for item in sorted(group)],
                    } for group in groups.values()])
    return representatives, metadata


def rune_segments(raw: str) -> list[list[int]]:
    """Split a raw page into contiguous rune words while preserving raw input elsewhere."""
    segments: list[list[int]] = []
    current: list[int] = []
    for char in raw:
        if char in RUNES:
            current.append(RUNES.index(char))
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments


def build_language_model(training_text: str) -> dict:
    """Build a fixed 29-symbol first-order model with add-one smoothing."""
    starts = [0] * MODULUS
    transitions = [[0] * MODULUS for _ in range(MODULUS)]
    total_symbols = 0
    words = re.findall(r"[A-Za-z]+", training_text)
    encoded = [encode_text(word) for word in words]
    encoded = [word for word in encoded if word]
    for word in encoded:
        starts[word[0]] += 1
        total_symbols += len(word)
        for left, right in zip(word, word[1:]):
            transitions[left][right] += 1
    start_denominator = sum(starts) + MODULUS
    start_weights = [math.log((count + 1) / start_denominator) for count in starts]
    transition_weights = []
    for row in transitions:
        denominator = sum(row) + MODULUS
        transition_weights.append([math.log((count + 1) / denominator) for count in row])
    return dict(schema=1, alphabet=MODULUS, smoothing="add_one",
                training_word_count=len(encoded), training_symbol_count=total_symbols,
                start_counts=starts, transition_counts=transitions,
                start_weights=start_weights, transition_weights=transition_weights)


def score_sequence(values: list[int], model: dict) -> float:
    if not values:
        return float("-inf")
    total = model["start_weights"][values[0]]
    weights = model["transition_weights"]
    for left, right in zip(values, values[1:]):
        total += weights[left][right]
    return total / len(values)


def _logadd(left: float, right: float) -> float:
    if left == float("-inf"):
        return right
    if right == float("-inf"):
        return left
    if left < right:
        left, right = right, left
    return left + math.log1p(math.exp(right - left))


def _state_delta(operator: str, clock: int) -> int:
    if operator == "DIVINITY":
        return DIVINITY[clock % len(DIVINITY)]
    if operator == "PRIME_MINUS_ONE":
        return primes(clock + 1)[clock] - 1
    raise ValueError(f"not a state operator: {operator}")


def _score_stateful(values: list[int], recipe: tuple[str, ...], model: dict) -> dict:
    state_positions = [i for i, operator in enumerate(recipe) if operator in STATE_OPERATORS]
    if len(state_positions) != 1:
        raise ValueError("stateful scorer requires exactly one state operator")
    state_at = state_positions[0]
    before = tuple(recipe[:state_at])
    state_operator = recipe[state_at]
    after = tuple(recipe[state_at + 1:])
    transformed = apply_recipe(values, before)
    # state -> post-map is incorporated into emissions; no path is selected.
    paths: dict[tuple[int, int | None], tuple[float, int]] = {(0, None): (0.0, 1)}
    start_weights = model["start_weights"]
    transition_weights = model["transition_weights"]
    for position, ciphertext in enumerate(transformed):
        next_paths: dict[tuple[int, int], tuple[float, int]] = {}
        for (clock, previous), (log_mass, path_count) in paths.items():
            options: list[tuple[int, int]] = []
            if ciphertext == 0:
                options.append((0, clock))  # clear F, no clock consumption
            normal = (ciphertext - _state_delta(state_operator, clock)) % MODULUS
            if normal != 0:
                options.append((normal, clock + 1))
            for state_value, next_clock in options:
                output = state_value
                for operator in after:
                    output = _point_value(output, operator, position)
                emission = (start_weights[output] if previous is None
                            else transition_weights[previous][output])
                key = (next_clock, output)
                old_log, old_count = next_paths.get(key, (float("-inf"), 0))
                next_paths[key] = (_logadd(old_log, log_mass + emission),
                                   old_count + path_count)
        paths = next_paths
        if not paths:
            return dict(score=float("-inf"), path_count=0, terminal_states=0,
                        final_clocks=[])
    total_log = float("-inf")
    total_paths = 0
    for log_mass, path_count in paths.values():
        total_log = _logadd(total_log, log_mass)
        total_paths += path_count
    return dict(score=total_log / len(values), path_count=total_paths,
                terminal_states=len(paths), final_clocks=sorted({clock for clock, _ in paths}))


def score_recipe(values: list[int], recipe: tuple[str, ...], model: dict) -> dict:
    if not values or any(type(value) is not int or not 0 <= value < MODULUS for value in values):
        raise ValueError("rune sequence must be non-empty and in 0..28")
    state_count = sum(operator in STATE_OPERATORS for operator in recipe)
    if state_count == 0:
        decoded = apply_recipe(values, recipe)
        return dict(score=score_sequence(decoded, model), path_count=1,
                    terminal_states=1, final_clocks=[len(values)], decoded=decoded)
    return _score_stateful(values, recipe, model)


def best_program(page_values: list[int], programs: list[tuple[str, ...]], model: dict) -> dict:
    rows = []
    for recipe in programs:
        result = score_recipe(page_values, recipe, model)
        rows.append(dict(program=list(recipe), depth=len(recipe), **{
            key: value for key, value in result.items() if key != "decoded"
        }))
    rows.sort(key=lambda row: (-row["score"], row["depth"], row["program"]))
    return dict(selected=rows[0], rankings=rows)


def permute_segments(segments: list[list[int]], rng) -> list[list[int]]:
    result = []
    for segment in segments:
        copy = list(segment)
        rng.shuffle(copy)
        result.append(copy)
    return result


def apply_symbol_permutation(values: list[int], permutation: list[int]) -> list[int]:
    if len(permutation) != MODULUS or sorted(permutation) != list(range(MODULUS)):
        raise ValueError("permutation must be a 29-symbol bijection")
    return [permutation[value] for value in values]
