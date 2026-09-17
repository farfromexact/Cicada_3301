"""Finite-state reachability for the registered plaintext-F clock model.

The input is ciphertext rune indices only.  A state is the consumed prime
stream position ``t`` after the already processed prefix.  For ciphertext
index zero there are two registered transitions: plaintext F copied without
consuming the stream, or an ordinary non-F inverse step that consumes it.
All other ciphertext values have one ordinary transition, and that transition
is rejected when it would decode to plaintext F.
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence


def prime_deltas(count: int) -> tuple[int, ...]:
    """Return ``(prime[t] - 1) mod 29`` for ``0 <= t < count``.

    This local sieve keeps the worker independent from source files and from
    the GP table.  The adaptive bound is deterministic and only increases if
    the conservative first estimate is insufficient.
    """
    if type(count) is not int or count < 0:
        raise ValueError("Prime count must be a nonnegative integer")
    if count == 0:
        return ()
    bound = max(128, count * 20)
    while True:
        sieve = bytearray(b"\x01") * bound
        sieve[:2] = b"\x00\x00"
        limit = math.isqrt(bound - 1)
        for p in range(2, limit + 1):
            if sieve[p]:
                sieve[p * p:bound:p] = b"\x00" * len(range(p * p, bound, p))
        values = [n for n, flag in enumerate(sieve) if flag]
        if len(values) >= count:
            return tuple((p - 1) % 29 for p in values[:count])
        bound *= 2


def _mask_digest(masks: Sequence[int], width: int) -> str:
    digest = hashlib.sha256()
    for mask in masks:
        digest.update(mask.to_bytes(width, "little"))
    return digest.hexdigest()


def scan_cipher(
    cipher: Sequence[int],
    *,
    start_clocks: Iterable[int] = (0,),
    deltas: Sequence[int] | None = None,
) -> dict:
    """Scan one ciphertext and merge states with the same clock position.

    ``ways`` is capped at two per state.  It is only an ambiguity diagnostic;
    no plaintext path is selected or scored by this module.
    """
    if not isinstance(cipher, (list, tuple)) or any(
        type(value) is not int or not 0 <= value < 29 for value in cipher
    ):
        raise ValueError("Cipher must contain rune indices 0..28")
    starts = tuple(start_clocks)
    if len(set(starts)) != len(starts) or any(
        type(value) is not int or value < 0 for value in starts
    ):
        raise ValueError("Start clocks must be distinct nonnegative integers")
    if deltas is None:
        deltas = prime_deltas(len(cipher))
    if len(deltas) < len(cipher) or any(
        type(value) is not int or not 0 <= value < 29 for value in deltas
    ):
        raise ValueError("Delta stream is shorter than the ciphertext or invalid")
    if any(value >= len(deltas) for value in starts):
        raise ValueError("Start clock exceeds the supplied stream")

    # A bit at t denotes a reachable state before the next rune.  The final
    # state may be t == len(deltas), hence the extra bit in the masks.
    max_clock = max(len(deltas), max(starts, default=0))
    width = max_clock // 8 + 1
    all_before_final = (1 << len(deltas)) - 1
    nonzero_delta = 0
    valid_by_cipher = [0] * 29
    for t, delta in enumerate(deltas):
        bit = 1 << t
        if delta != 0:
            nonzero_delta |= bit
        for cipher_value in range(1, 29):
            if cipher_value != delta:
                valid_by_cipher[cipher_value] |= bit

    state_mask = sum(1 << value for value in starts)
    ways = {value: 1 for value in starts}
    history = [state_mask]
    state_counts = [state_mask.bit_count()]
    ordinary_edges = 0
    exception_edges = 0
    first_dead_position = None

    for position, cipher_value in enumerate(cipher):
        available = state_mask & all_before_final
        if cipher_value == 0:
            # The copy-F edge leaves t unchanged.  The ordinary edge is legal
            # only when -delta[t] is a nonzero plaintext value.
            exception_edges += available.bit_count()
            ordinary = available & nonzero_delta
            ordinary_edges += ordinary.bit_count()
            next_mask = available | (ordinary << 1)
        else:
            ordinary = available & valid_by_cipher[cipher_value]
            ordinary_edges += ordinary.bit_count()
            next_mask = ordinary << 1

        next_ways: dict[int, int] = {}
        for clock, count in ways.items():
            delta = deltas[clock]
            if cipher_value == 0:
                next_ways[clock] = min(2, next_ways.get(clock, 0) + count)
                if delta != 0:
                    next_ways[clock + 1] = min(
                        2, next_ways.get(clock + 1, 0) + count
                    )
            elif cipher_value != delta:
                next_ways[clock + 1] = min(
                    2, next_ways.get(clock + 1, 0) + count
                )
        state_mask = next_mask
        ways = next_ways
        history.append(state_mask)
        state_counts.append(state_mask.bit_count())
        if not state_mask and first_dead_position is None:
            first_dead_position = position

    terminal_paths = min(2, sum(ways.values()))
    return dict(
        initial_clocks=sorted(starts),
        rune_count=len(cipher),
        zero_cipher_runes=sum(value == 0 for value in cipher),
        state_counts=state_counts,
        max_state_count=max(state_counts, default=0),
        final_clocks=sorted(ways),
        final_state_count=len(ways),
        terminal_path_count_capped=terminal_paths,
        unique_terminal_path=(len(ways) == 1 and terminal_paths == 1),
        ordinary_edges=ordinary_edges,
        exception_edges=exception_edges,
        total_edges=ordinary_edges + exception_edges,
        first_dead_position=first_dead_position,
        state_digest=_mask_digest(history, width),
    )
