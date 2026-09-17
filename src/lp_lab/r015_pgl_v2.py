"""The public PGL(2,29) enumeration for R015-C.

Point 29 is infinity.  The module is intentionally self-contained and does
not read the corpus or any verifier-only material.
"""

from __future__ import annotations

import math


MODULUS = 29
INFINITY = 29
PGL_ORDER = MODULUS * (MODULUS * MODULUS - 1)


def matrices() -> list[tuple[int, int, int, int]]:
    """Return one deterministic representative for every PGL element."""
    result = []
    for a in range(1, MODULUS):
        for b in range(MODULUS):
            result.append((a, b, 0, 1))
    for a in range(MODULUS):
        for d in range(MODULUS):
            for b in range(MODULUS):
                if b != (a * d) % MODULUS:
                    result.append((a, b, 1, d))
    if len(result) != PGL_ORDER or len(set(result)) != PGL_ORDER:
        raise AssertionError("PGL representative count is not 24360")
    return result


def image(point: int, matrix: tuple[int, int, int, int]) -> int:
    if type(point) is not int or not 0 <= point <= INFINITY:
        raise ValueError("projective point must be 0..29, with 29=infinity")
    a, b, c, d = matrix
    if math.gcd((a * d - b * c) % MODULUS, MODULUS) != 1:
        raise ValueError("matrix must have non-zero determinant")
    if point == INFINITY:
        return (a * pow(c, MODULUS - 2, MODULUS)) % MODULUS if c else INFINITY
    denominator = (c * point + d) % MODULUS
    if denominator == 0:
        return INFINITY
    return ((a * point + b) * pow(denominator, MODULUS - 2, MODULUS)) % MODULUS


def mapping(matrix: tuple[int, int, int, int]) -> tuple[int, ...]:
    return tuple(image(point, matrix) for point in range(INFINITY + 1))


def inverse_mapping(table: tuple[int, ...]) -> tuple[int, ...]:
    if sorted(table) != list(range(INFINITY + 1)):
        raise ValueError("PGL table must be a projective-line bijection")
    inverse = [0] * (INFINITY + 1)
    for source, target in enumerate(table):
        inverse[target] = source
    return tuple(inverse)


def segment_points(raw: str, runes: str) -> tuple[list[list[int]], dict]:
    """Map '-' to infinity and keep slash/formatting as side metadata.

    Slash and ASCII formatting whitespace do not become points and do not
    break a model segment.  Other non-rune literals are hard boundaries and
    are never silently converted to rune values.
    """
    segments: list[list[int]] = []
    current: list[int] = []
    counts = {"runes": 0, "literal_separator": 0, "slash_boundaries": 0,
              "other_hard_boundaries": 0, "formatting_boundaries": 0}
    for char in raw:
        if char in runes:
            current.append(runes.index(char))
            counts["runes"] += 1
        elif char == "-":
            current.append(INFINITY)
            counts["literal_separator"] += 1
        elif char in "/\r\n\t ":
            if char == "/":
                counts["slash_boundaries"] += 1
            else:
                counts["formatting_boundaries"] += 1
        else:
            if current:
                segments.append(current)
                current = []
            counts["other_hard_boundaries"] += 1
    if current:
        segments.append(current)
    counts.update(segment_count=len(segments), point_count=sum(map(len, segments)))
    return segments, counts


def model_from_training(segments: list[list[int]]) -> dict:
    starts = [0] * (MODULUS + 1)
    transitions = [[0] * (MODULUS + 1) for _ in range(MODULUS + 1)]
    for segment in segments:
        if not segment:
            continue
        starts[segment[0]] += 1
        for left, right in zip(segment, segment[1:]):
            transitions[left][right] += 1
    start_denominator = sum(starts) + MODULUS + 1
    start_weights = [[math.log((count + 1) / start_denominator) for count in starts]][0]
    transition_weights = []
    for row in transitions:
        denominator = sum(row) + MODULUS + 1
        transition_weights.append([math.log((count + 1) / denominator) for count in row])
    return dict(alphabet=MODULUS + 1, smoothing="add_one", start_counts=starts,
                transition_counts=transitions, start_weights=start_weights,
                transition_weights=transition_weights)


def pair_counts(segments: list[list[int]]) -> tuple[list[int], list[list[int]], int]:
    starts = [0] * (MODULUS + 1)
    transitions = [[0] * (MODULUS + 1) for _ in range(MODULUS + 1)]
    points = 0
    for segment in segments:
        if not segment:
            continue
        starts[segment[0]] += 1
        points += len(segment)
        for left, right in zip(segment, segment[1:]):
            transitions[left][right] += 1
    return starts, transitions, points


def score_counts(table: tuple[int, ...], counts: tuple[list[int], list[list[int]], int],
                 model: dict) -> float:
    starts, transitions, points = counts
    if points == 0:
        return float("-inf")
    total = sum(count * model["start_weights"][table[index]]
                for index, count in enumerate(starts))
    weights = model["transition_weights"]
    for left in range(INFINITY + 1):
        for right in range(INFINITY + 1):
            count = transitions[left][right]
            if count:
                total += count * weights[table[left]][table[right]]
    return total / points


def permute_segments(segments: list[list[int]], rng) -> list[list[int]]:
    result = []
    for segment in segments:
        copy = list(segment)
        rng.shuffle(copy)
        result.append(copy)
    return result


def apply_s30(segments: list[list[int]], permutation: list[int]) -> list[list[int]]:
    if len(permutation) != INFINITY + 1 or sorted(permutation) != list(range(INFINITY + 1)):
        raise ValueError("S30 map must be a 30-point bijection")
    return [[permutation[value] for value in segment] for segment in segments]
