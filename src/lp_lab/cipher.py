from .runes import RUNES, primes, display

def transform(tokens, *, mode="prime", offset=0, shift=1, skip=(), encrypt=False):
    """C=P+(prime-shift) mod 29; skips preserve rune AND do not consume prime."""
    if mode not in ("prime", "identity") or offset < 0:
        raise ValueError("Unsupported transform")
    n = sum(t["kind"] == "rune" for t in tokens)
    if len(set(skip)) != len(skip) or any(i < 0 or i >= n for i in skip):
        raise ValueError("Skip must contain unique valid rune ordinals")
    ps, stream, steps, out, latin = primes(n + offset), 0, [], [], []
    for t in tokens:
        if t["kind"] != "rune":
            out.append(t["raw"])
            latin.append(t["raw"])
            continue
        ordinal, value = t["rune_ordinal"], t["rune"]["index"]
        consume = mode == "prime" and ordinal not in skip
        p = ps[offset + stream] if consume else None
        delta = (p - shift) % 29 if consume else 0
        target = (value + (delta if encrypt else -delta)) % 29
        steps.append(dict(token_id=t["id"], rune_ordinal=ordinal, input_rune=t["raw"], input_index=value,
                          stream_index=offset+stream if consume else None, prime=p, delta=delta,
                          skipped=ordinal in skip, output_index=target, output_rune=RUNES[target],
                          latin=display(target), image=t["image"]))
        out.append(RUNES[target])
        latin.append(display(target))
        stream += int(consume)
    return dict(raw="".join(out), latin="".join(latin), steps=steps, primes_consumed=stream)
