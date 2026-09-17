"""H016-v2 finite-state inverse with explicit cross-page path counts.

The state is only a set of reachable key phases plus a capped path count for
each phase.  No plaintext path is selected or emitted by this module.
"""

from __future__ import annotations

import hashlib


DEFAULT_KEY = (0, 10, 4, 0, 1, 19, 0, 18, 4, 18, 9, 0, 18)
PATH_CAP = 2


def _validate_key(key):
    if not isinstance(key, (list, tuple)) or not key:
        raise ValueError("Key must be a non-empty sequence")
    if any(type(value) is not int or not 0 <= value < 29 for value in key):
        raise ValueError("Key values must be rune indices 0..28")
    return tuple(key)


def _validate_starts(start_phases, initial_ways, key_length):
    starts = tuple(start_phases)
    if len(set(starts)) != len(starts) or any(
        type(value) is not int or not 0 <= value < key_length for value in starts
    ):
        raise ValueError("Start phases must be distinct indices in the key")
    if initial_ways is None:
        ways = {phase: 1 for phase in starts}
    else:
        if not isinstance(initial_ways, dict):
            raise ValueError("Initial path counts must be a phase-to-count mapping")
        if set(initial_ways) != set(starts):
            raise ValueError("Initial path counts must match start phases")
        ways = {}
        for phase in starts:
            count = initial_ways[phase]
            if type(count) is not int or not 1 <= count <= PATH_CAP:
                raise ValueError("Initial path counts must be capped positive integers")
            ways[phase] = count
    return starts, ways


def _digest_history(history):
    digest = hashlib.sha256()
    for mask in history:
        digest.update(mask.to_bytes(2, "little"))
    return digest.hexdigest()


def _count_list(counts):
    return [[phase, counts[phase]] for phase in sorted(counts)]


def scan_page(cipher, *, start_phases=(0,), initial_ways=None, key=DEFAULT_KEY):
    """Scan one rune sequence without choosing a plaintext path.

    For input ciphertext ``0`` both legal inverse edges are retained when
    available: copied plaintext-F keeps the phase, while an ordinary non-F
    inverse consumes one phase.  A normal inverse that would emit plaintext-F
    is rejected.  ``initial_ways`` lets a continuous caller carry ambiguity
    across a page boundary; counts are capped at two.
    """
    if not isinstance(cipher, (list, tuple)) or any(
        type(value) is not int or not 0 <= value < 29 for value in cipher
    ):
        raise ValueError("Cipher must contain rune indices 0..28")
    key = _validate_key(key)
    starts, ways = _validate_starts(start_phases, initial_ways, len(key))
    initial_counts = dict(ways)
    states = set(starts)
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
            incoming = ways[phase]
            if cipher_value == 0:
                # Copied plaintext F: retain the phase without consuming it.
                exception_edges += 1
                next_states.add(phase)
                next_ways[phase] = min(
                    PATH_CAP, next_ways.get(phase, 0) + incoming
                )
                # Ordinary inverse is legal only when it emits a non-F rune.
                if delta != 0:
                    next_phase = (phase + 1) % len(key)
                    ordinary_edges += 1
                    next_states.add(next_phase)
                    next_ways[next_phase] = min(
                        PATH_CAP, next_ways.get(next_phase, 0) + incoming
                    )
            elif cipher_value != delta:
                # The ordinary inverse emits a non-F rune and consumes phase.
                next_phase = (phase + 1) % len(key)
                ordinary_edges += 1
                next_states.add(next_phase)
                next_ways[next_phase] = min(
                    PATH_CAP, next_ways.get(next_phase, 0) + incoming
                )
        states = next_states
        ways = next_ways
        history.append(sum(1 << phase for phase in states))
        state_counts.append(len(states))
        if not states and first_dead_position is None:
            first_dead_position = position

    if not starts:
        legal_prefix_length = None
        legal_prefix_ratio = None
    else:
        legal_prefix_length = (
            len(cipher) if first_dead_position is None else first_dead_position
        )
        legal_prefix_ratio = legal_prefix_length / len(cipher) if cipher else 1.0
    terminal_paths = min(PATH_CAP, sum(ways.values()))
    model_status = "compatible" if states else ("not_reached" if not starts else "dead")
    return {
        "initial_phases": sorted(starts),
        "initial_path_counts": _count_list(initial_counts),
        "rune_count": len(cipher),
        "input_zero_runes": sum(value == 0 for value in cipher),
        "state_counts": state_counts,
        "max_state_count": max(state_counts, default=0),
        "final_phases": sorted(ways),
        "final_path_counts": _count_list(ways),
        "final_state_count": len(ways),
        "terminal_path_count_capped": terminal_paths,
        "unique_terminal_path": len(ways) == 1 and terminal_paths == 1,
        "ordinary_edges": ordinary_edges,
        "exception_edges": exception_edges,
        "total_edges": ordinary_edges + exception_edges,
        "first_dead_position": first_dead_position,
        "legal_prefix_length": legal_prefix_length,
        "legal_prefix_ratio": legal_prefix_ratio,
        "model_status": model_status,
        "state_digest": _digest_history(history),
    }
