"""Public Berlekamp--Massey primitives for R015-B.

The worker imports this module with no corpus access.  The runner has a
separate implementation for its independent arithmetic check.
"""

from __future__ import annotations

from .runes import GP


MODULUS = 29
MIN_LENGTH = 96
MAX_ORDER = 16


def _validate(sequence: list[int]) -> None:
    if any(type(value) is not int or not 0 <= value < MODULUS for value in sequence):
        raise ValueError("sequence values must be in F29")


def berlekamp_massey(sequence: list[int]) -> dict:
    """Return the shortest recurrence ``s[n]+sum(c[j]s[n-j])=0`` over F29."""
    _validate(sequence)
    connection = [1]
    backup = [1]
    order = 0
    shift = 1
    last_discrepancy = 1
    for n, value in enumerate(sequence):
        discrepancy = value
        for j in range(1, order + 1):
            discrepancy = (discrepancy + connection[j] * sequence[n - j]) % MODULUS
        if discrepancy == 0:
            shift += 1
            continue
        previous = connection[:]
        scale = discrepancy * pow(last_discrepancy, MODULUS - 2, MODULUS) % MODULUS
        required = len(backup) + shift
        if len(connection) < required:
            connection.extend([0] * (required - len(connection)))
        for j, coefficient in enumerate(backup):
            connection[j + shift] = (connection[j + shift] - scale * coefficient) % MODULUS
        if 2 * order <= n:
            order = n + 1 - order
            backup = previous
            last_discrepancy = discrepancy
            shift = 1
        else:
            shift += 1
    connection = connection[:order + 1]
    if len(sequence) == 0:
        order = 0
        connection = [1]
    return dict(order=order, connection=connection,
                recurrence="s[n]+sum(connection[j]*s[n-j] for j=1..L)=0 mod29")


def recurrence_holds(sequence: list[int], connection: list[int]) -> bool:
    _validate(sequence)
    order = len(connection) - 1
    if not connection or connection[0] % MODULUS != 1:
        return False
    return all((sum(connection[j] * sequence[n - j] for j in range(order + 1))
                % MODULUS) == 0 for n in range(order, len(sequence)))


def predict_suffix(prefix: list[int], suffix_length: int, connection: list[int]) -> list[int]:
    _validate(prefix)
    order = len(connection) - 1
    if order == 0:
        return [0] * suffix_length
    if len(prefix) < order or suffix_length < 0:
        raise ValueError("invalid prefix/order or suffix length")
    values = list(prefix)
    for _ in range(suffix_length):
        next_value = (-sum(connection[j] * values[-j]
                            for j in range(1, order + 1))) % MODULUS
        values.append(next_value)
    return values[len(prefix):]


def metrics(sequence: list[int]) -> dict:
    _validate(sequence)
    n = len(sequence)
    if n < MIN_LENGTH:
        bm = berlekamp_massey(sequence)
        return dict(status="inconclusive_short", length=n, order=bm["order"],
                    connection=bm["connection"], prefix_length=None,
                    suffix_length=None, predicted_hits=None, prediction_rate=None,
                    predicted_suffix=[], t_l=None, t_p=None)
    prefix_length = (2 * n) // 3
    suffix_length = n - prefix_length
    max_order = min(MAX_ORDER, prefix_length // 4)
    prefix = sequence[:prefix_length]
    bm = berlekamp_massey(prefix)
    order = bm["order"]
    if order <= max_order:
        prediction = predict_suffix(prefix, suffix_length, bm["connection"])
        actual = sequence[prefix_length:]
        hits = sum(left == right for left, right in zip(prediction, actual))
        prediction_rate = hits / suffix_length
    else:
        prediction = []
        hits = 0
        prediction_rate = 0.0
    t_l = 1.0 - 2.0 * order / prefix_length
    t_p = prediction_rate
    return dict(status="eligible", length=n, prefix_length=prefix_length,
                suffix_length=suffix_length, max_order=max_order, order=order,
                register_length=order, connection=bm["connection"],
                recurrence_holds=recurrence_holds(prefix, bm["connection"]),
                predicted_suffix=prediction, predicted_hits=hits,
                prediction_rate=prediction_rate, t_l=t_l, t_p=t_p,
                full_order=berlekamp_massey(sequence)["order"])


def independent_prime_values(count: int) -> list[int]:
    result = []
    candidate = 2
    while len(result) < count:
        if all(candidate % divisor for divisor in result if divisor * divisor <= candidate):
            result.append(candidate)
        candidate += 1
    return result


def views(cipher: list[int]) -> dict[str, list[int]]:
    _validate(cipher)
    position_primes = independent_prime_values(len(cipher))
    gp_projection = [GP[value] % MODULUS for value in cipher]
    gp_totient_projection = [(GP[value] - 1) % MODULUS for value in cipher]
    prime_residual = [(value - position_primes[i]) % MODULUS
                      for i, value in enumerate(cipher)]
    totient_residual = [(value - (position_primes[i] - 1)) % MODULUS
                        for i, value in enumerate(cipher)]
    return {
        "raw": list(cipher),
        "difference": [(right - left) % MODULUS for left, right in zip(cipher, cipher[1:])],
        "gp_projection": gp_projection,
        "gp_totient_projection": gp_totient_projection,
        "position_prime_residual": prime_residual,
        "position_totient_residual": totient_residual,
    }
