"""Exact integer acceleration of the frozen H030-v2 BM arithmetic.

No RNG, corpus, gate labels or scoring decisions enter this module. Arrays
hold the same polynomial coefficients as the original dynamic lists. Integer
summation followed by one reduction is identical in F29 to per-term reduction.
"""
from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=False)
def _bm(sequence):
    n = len(sequence)
    c = np.zeros(n + 1, dtype=np.int64)
    b = np.zeros(n + 1, dtype=np.int64)
    c[0] = b[0] = 1
    c_len = b_len = 1
    order, shift, last = 0, 1, 1
    for index in range(n):
        discrepancy = sequence[index]
        for j in range(1, order + 1):
            discrepancy += c[j] * sequence[index - j]
        discrepancy %= 29
        if discrepancy == 0:
            shift += 1
            continue
        previous = c.copy()
        previous_len = c_len
        inverse = 1
        for _ in range(27):
            inverse = inverse * last % 29
        scale = discrepancy * inverse % 29
        c_len = max(c_len, b_len + shift)
        for j in range(b_len):
            c[j + shift] = (c[j + shift] - scale * b[j]) % 29
        if 2 * order <= index:
            order = index + 1 - order
            b = previous
            b_len = previous_len
            last = discrepancy
            shift = 1
        else:
            shift += 1
    return order, c[:order + 1]


@njit(cache=False)
def _holds(sequence, connection):
    order = len(connection) - 1
    for index in range(order, len(sequence)):
        value = 0
        for j in range(order + 1):
            value += connection[j] * sequence[index - j]
        if value % 29:
            return False
    return True


def bm(sequence):
    if any(type(value) is not int or not 0 <= value < 29 for value in sequence):
        raise ValueError("BM sequence outside F29")
    order, connection = _bm(np.asarray(sequence, dtype=np.int64))
    return {"order": int(order), "connection": connection.tolist()}


def metrics(sequence):
    full = bm(sequence)
    n = len(sequence)
    if n < 96:
        return dict(status="inconclusive_short", length=n, order=full["order"],
                    max_order=None, predicted_hits=None, suffix_length=None,
                    t_l=None, t_p=None, full_order=full["order"],
                    recurrence_holds=bool(_holds(np.asarray(sequence, dtype=np.int64),
                                               np.asarray(full["connection"], dtype=np.int64))))
    m = 2 * n // 3
    fit = bm(sequence[:m])
    order = fit["order"]
    cap = min(16, m // 4)
    hits = 0
    if order <= cap:
        predicted = list(sequence[:m])
        for _ in range(n - m):
            predicted.append((-sum(fit["connection"][j] * predicted[-j]
                                   for j in range(1, order + 1))) % 29)
        hits = sum(a == b for a, b in zip(predicted[m:], sequence[m:]))
    return dict(status="eligible", length=n, order=order, max_order=cap,
                predicted_hits=hits, suffix_length=n - m, t_l=1.0 - 2.0 * order / m,
                t_p=hits / (n - m), full_order=full["order"],
                recurrence_holds=bool(_holds(np.asarray(sequence[:m], dtype=np.int64),
                                           np.asarray(fit["connection"], dtype=np.int64))))


def consistent_recurrence(sequence, order):
    """Finite-field linear-system oracle, independent of the BM algorithm."""
    if order == 0:
        return not any(sequence)
    matrix = [[sequence[t - j] for j in range(1, order + 1)] + [(-sequence[t]) % 29]
              for t in range(order, len(sequence))]
    pivot = 0
    for column in range(order):
        chosen = next((row for row in range(pivot, len(matrix)) if matrix[row][column]), None)
        if chosen is None:
            continue
        matrix[pivot], matrix[chosen] = matrix[chosen], matrix[pivot]
        scale = pow(matrix[pivot][column], -1, 29)
        matrix[pivot] = [value * scale % 29 for value in matrix[pivot]]
        for row in range(pivot + 1, len(matrix)):
            scale = matrix[row][column]
            if scale:
                matrix[row] = [(a - scale * b) % 29 for a, b in zip(matrix[row], matrix[pivot])]
        pivot += 1
    return not any(not any(row[:order]) and row[-1] for row in matrix)
