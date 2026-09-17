"""Pure H002 clock conventions; no source, reference, answer or file access.

Rune ordinals and raw Unicode codepoint offsets are distinct. Defaults describe
the frozen LP2/56 input; toy tests may override its known exception/boundaries.
"""
from .runes import RUNES, primes


BRANCHES = (
    "continuous", "line_reset", "paragraph_reset", "title_reset",
    "hash_advance", "delimiter_advance",
)
HASH_SPANS = ((67, 93), (95, 120), (122, 147), (149, 176), (178, 203))
PUNCTUATION = frozenset("-.,/&$§%;")
HEX = frozenset("0123456789abcdef")


def transform(raw, branch, *, skip_ordinal=56, title_boundary=8,
              hash_spans=HASH_SPANS, encrypt=False):
    """Return exact raw output, rune arithmetic steps and clock-only events.

The skip is a fixed ordinal, including on inverse encryption, not a test of the
current glyph value. ``None`` disables the exception for hand-computed tests.
Hash spans and title offsets are checked only by their applicable branches.
"""
    if not isinstance(raw, str) or branch not in BRANCHES:
        raise ValueError("Expected raw text and one registered H002 branch")
    rune_count = sum(char in RUNES for char in raw)
    if skip_ordinal is not None and (
        type(skip_ordinal) is not int or not 0 <= skip_ordinal < rune_count
    ):
        raise ValueError("Skip must be None or one valid fixed rune ordinal")
    for offset, char in enumerate(raw):
        if 0x16A0 <= ord(char) <= 0x16FF and char not in RUNES:
            raise ValueError(f"Unregistered rune {char!r} at {offset}")
    if branch == "title_reset" and (
        type(title_boundary) is not int or not 0 <= title_boundary < len(raw)
    ):
        raise ValueError("Title boundary must be an existing raw codepoint offset")
    hash_offsets = set()
    if branch == "hash_advance":
        previous_end = 0
        for span in hash_spans:
            if not isinstance(span, (tuple, list)) or len(span) != 2:
                raise ValueError("Hash spans must be half-open offset pairs")
            start, end = span
            if (type(start) is not int or type(end) is not int
                    or not previous_end <= start < end <= len(raw)):
                raise ValueError("Hash spans must be ordered, disjoint and in bounds")
            if any(char not in HEX for char in raw[start:end]):
                raise ValueError("Registered hash span contains a non-hex character")
            hash_offsets.update(range(start, end))
            previous_end = end

    # Each raw codepoint can consume at most one slot; resets only lower t.
    prime_values = primes(len(raw) + 1)
    clock, ordinal, out, output_indices, steps, events = 0, 0, [], [], [], []
    for source_offset, char in enumerate(raw):
        if branch == "title_reset" and source_offset == title_boundary:
            events.append(dict(event="reset", reason="title_boundary",
                               source_offset=source_offset, raw=char,
                               timing="before", clock_before=clock, clock_after=0))
            clock = 0
        if char in RUNES:
            value = RUNES.index(char)
            skipped = ordinal == skip_ordinal
            clock_before = clock
            stream_index = None if skipped else clock
            prime = None if skipped else prime_values[clock]
            delta = 0 if skipped else (prime - 1) % 29
            target = (value + delta if encrypt else value - delta) % 29
            if not skipped:
                clock += 1
            steps.append(dict(source_offset=source_offset, rune_ordinal=ordinal,
                              input_rune=char, input_index=value,
                              output_rune=RUNES[target], output_index=target,
                              stream_index=stream_index, prime=prime, delta=delta,
                              skipped=skipped, clock_before=clock_before,
                              clock_after=clock))
            out.append(RUNES[target])
            output_indices.append(target)
            ordinal += 1
            continue

        out.append(char)
        reset = ((branch == "line_reset" and char == "/")
                 or (branch == "paragraph_reset" and char == "&"))
        if reset:
            events.append(dict(event="reset", reason=branch, raw=char,
                               source_offset=source_offset, timing="after",
                               clock_before=clock, clock_after=0))
            clock = 0
        advance = ((branch == "hash_advance" and source_offset in hash_offsets)
                   or (branch == "delimiter_advance" and char in PUNCTUATION))
        if advance:
            events.append(dict(event="advance", reason=branch, raw=char,
                               source_offset=source_offset, timing="after",
                               stream_index=clock, prime=prime_values[clock],
                               clock_before=clock, clock_after=clock + 1))
            clock += 1
    return dict(raw="".join(out), indices=output_indices, steps=steps,
                events=events, final_clock=clock)
