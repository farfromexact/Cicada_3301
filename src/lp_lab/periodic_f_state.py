"""Pure H016 finite-state inverse for a fixed periodic key and plaintext-F exception."""

from __future__ import annotations

import hashlib


DEFAULT_KEY = (0, 10, 4, 0, 1, 19, 0, 18, 4, 18, 9, 0, 18)


def _validate_key(key):
    if not isinstance(key, (list, tuple)) or not key:
        raise ValueError("Key must be a non-empty sequence")
    if any(type(value) is not int or not 0 <= value < 29 for value in key):
        raise ValueError("Key values must be rune indices 0..28")
    return tuple(key)


def _digest_history(history):
    digest = hashlib.sha256()
    for mask in history:
        digest.update(mask.to_bytes(2, "little"))
    return digest.hexdigest()


def scan_page(cipher, *, start_phases=(0,), key=DEFAULT_KEY):
    """Return reachable key phases without selecting or emitting a plaintext path.

    For ``c == 0`` the copied plaintext-F edge keeps the phase, while the
    ordinary inverse edge is retained only when it decodes to nonzero
    plaintext.  All other symbols have only the ordinary edge, which is
    rejected when it would decode to plaintext F.
    """
    if not isinstance(cipher, (list, tuple)) or any(
        type(value) is not int or not 0 <= value < 29 for value in cipher
    ):
        raise ValueError("Cipher must contain rune indices 0..28")
    key = _validate_key(key)
    starts = tuple(start_phases)
    if len(set(starts)) != len(starts) or any(
        type(value) is not int or not 0 <= value < len(key) for value in starts
    ):
        raise ValueError("Start phases must be distinct indices in the key")

    states = set(starts)
    ways = {phase: 1 for phase in starts}
    history = [sum(1 << phase for phase in states)]
    state_counts = [len(states)]
    ordinary_edges = 0
    exception_edges = 0
    first_dead_position = None

    for position, cipher_value in enumerate(cipher):
        next_states = set()
        next_ways = {}
        for phase in states:
            delta = key[phase]
            if cipher_value == 0:
                # Copied plaintext F: the clock is unchanged.
                exception_edges += 1
                next_states.add(phase)
                next_ways[phase] = min(2, next_ways.get(phase, 0) + ways[phase])
                # The ordinary inverse is legal exactly when -delta is nonzero.
                if delta != 0:
                    next_phase = (phase + 1) % len(key)
                    ordinary_edges += 1
                    next_states.add(next_phase)
                    next_ways[next_phase] = min(
                        2, next_ways.get(next_phase, 0) + ways[phase]
                    )
            elif cipher_value != delta:
                # p=(c-delta) mod29 is nonzero and consumes one phase.
                next_phase = (phase + 1) % len(key)
                ordinary_edges += 1
                next_states.add(next_phase)
                next_ways[next_phase] = min(
                    2, next_ways.get(next_phase, 0) + ways[phase]
                )
        states = next_states
        ways = next_ways
        history.append(sum(1 << phase for phase in states))
        state_counts.append(len(states))
        if not states and first_dead_position is None:
            first_dead_position = position

    legal_prefix_length = (
        len(cipher) if first_dead_position is None else first_dead_position
    )
    legal_prefix_ratio = (
        legal_prefix_length / len(cipher) if cipher else 1.0
    )
    terminal_paths = min(2, sum(ways.values()))
    return {
        "initial_phases": sorted(starts),
        "rune_count": len(cipher),
        "input_zero_runes": sum(value == 0 for value in cipher),
        "state_counts": state_counts,
        "max_state_count": max(state_counts, default=0),
        "final_phases": sorted(ways),
        "final_state_count": len(ways),
        "terminal_path_count_capped": terminal_paths,
        "unique_terminal_path": len(ways) == 1 and terminal_paths == 1,
        "ordinary_edges": ordinary_edges,
        "exception_edges": exception_edges,
        "total_edges": ordinary_edges + exception_edges,
        "first_dead_position": first_dead_position,
        "legal_prefix_length": legal_prefix_length,
        "legal_prefix_ratio": legal_prefix_ratio,
        "state_digest": _digest_history(history),
    }
