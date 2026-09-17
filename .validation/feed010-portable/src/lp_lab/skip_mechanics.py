"""Pure, registered H001 skip/clock transforms; no sources or answers are read."""
from .runes import RUNES

DIVINITY = (23, 10, 1, 10, 9, 10, 16, 26)
POLICIES = ("none", "specified_free", "specified_consume", "all_cipher_f_free")


def _primes(count):
    """Small bounded stream, generated from arithmetic alone."""
    result, candidate = [], 2
    while len(result) < count:
        if all(candidate % prime for prime in result if prime * prime <= candidate):
            result.append(candidate)
        candidate += 1
    return result


def transform(pages, *, mode="vigenere", direction="subtract", policy="none",
              continuity="continuous", specified_skip=(), key=DIVINITY):
    """Preserve literals and return every rune operation with global coordinates.

    The caller must supply ciphertext-only pages and frozen public parameters.
    Any inverse check must use the returned frozen delta/mask. In particular,
    rerunning all_cipher_f_free on plaintext is not an inverse operation.
    """
    if mode not in {"vigenere", "prime"}:
        raise ValueError("Unknown mode")
    if direction not in {"subtract", "add"}:
        raise ValueError("Unknown direction")
    if policy not in POLICIES:
        raise ValueError("Unknown skip policy")
    if continuity not in {"continuous", "page_reset"}:
        raise ValueError("Unknown continuity")
    if not isinstance(pages, list) or any(set(page) != {"page", "raw"} for page in pages):
        raise ValueError("Expected ciphertext-only pages with exactly page and raw fields")
    if any(not isinstance(page["page"], str) or not isinstance(page["raw"], str) for page in pages):
        raise ValueError("Page name and raw ciphertext must be strings")
    if len({page["page"] for page in pages}) != len(pages):
        raise ValueError("Page identifiers must be unique")
    for page in pages:
        for offset, char in enumerate(page["raw"]):
            if 0x16A0 <= ord(char) <= 0x16FF and char not in RUNES:
                raise ValueError(f"Unregistered rune {char!r} on {page['page']} at {offset}")
    total = sum(char in RUNES for page in pages for char in page["raw"])
    supplied = list(specified_skip)
    if (any(type(value) is not int or not 0 <= value < total for value in supplied)
            or len(set(supplied)) != len(supplied)):
        raise ValueError("Skip ordinals must be distinct in-range integers")
    if not key or any(type(value) is not int or not 0 <= value < 29 for value in key):
        raise ValueError("Key must contain rune indices 0..28")
    prescribed = set(supplied)
    prime_stream = _primes(total) if mode == "prime" else []
    clock = global_ordinal = 0
    steps, output_pages, selected = [], [], []
    sign = -1 if direction == "subtract" else 1
    for page in pages:
        if continuity == "page_reset":
            clock = 0
        local_ordinal = 0
        chars, values = [], []
        for source_offset, char in enumerate(page["raw"]):
            if char not in RUNES:
                chars.append(char)
                continue
            value = RUNES.index(char)
            skipped = ((policy in {"specified_free", "specified_consume"} and global_ordinal in prescribed)
                       or (policy == "all_cipher_f_free" and value == 0))
            consumed = not skipped or policy == "specified_consume"
            delta = 0 if skipped else (key[clock % len(key)] if mode == "vigenere" else prime_stream[clock] - 1)
            target = (value + sign * delta) % 29
            steps.append(dict(page=page["page"], source_offset=source_offset,
                              global_rune_ordinal=global_ordinal, local_rune_ordinal=local_ordinal,
                              input_index=value, output_index=target, clock_index=clock,
                              delta=delta, skipped=skipped, consumed=consumed))
            if skipped:
                selected.append(global_ordinal)
            chars.append(RUNES[target])
            values.append(target)
            clock += int(consumed)
            local_ordinal += 1
            global_ordinal += 1
        output_pages.append(dict(page=page["page"], raw="".join(chars), indices=values))
    return dict(pages=output_pages, steps=steps, selected_skips=selected, final_clock=clock)
