"""Lossless H008 input views; no candidate scoring or answer-file access.

Groups join rune positions across the registered soft separators only.  They
are rune-domain analysis spans, not reconstructed words or inferred chapters.
"""
import hashlib

from .runes import RUNES


SOFT_SEPARATORS = frozenset("-.,/")


def prepare_page(page):
    """Validate a retained page and derive fixed structural boundary masks.

    The original rune token dictionaries are returned unchanged.  Source raw
    text is never rewritten: all offsets continue to index the original raw.
    """
    raw, tokens = page["raw"], page["tokens"]
    if not isinstance(raw, str) or not isinstance(tokens, list):
        raise ValueError("Expected raw text and a lossless token list")
    if any(not isinstance(t.get("raw"), str) or len(t["raw"]) != 1 for t in tokens):
        raise ValueError("Expected one original codepoint per token")
    if "".join(t["raw"] for t in tokens) != raw:
        raise ValueError("Token stream does not preserve every raw codepoint")
    raw_sha = hashlib.sha256(raw.encode("utf8")).hexdigest()
    if page.get("raw_sha256", raw_sha) != raw_sha:
        raise ValueError("Raw text SHA-256 mismatch")

    values, rune_tokens, groups, hyphens, eligible, segments = [], [], [], [], [], []
    hard_breaks = []
    # A break starts a new group only when another rune actually follows it.
    pending_hard, pending_hyphen = True, False
    group = -1
    for offset, token in enumerate(tokens):
        if token.get("source_offset") != offset:
            raise ValueError("Token offset does not index the preserved raw text")
        if token.get("page") != page["page"]:
            raise ValueError("Token belongs to a different page")
        char = token["raw"]
        is_rune = char in RUNES
        if 0x16A0 <= ord(char) <= 0x16FF and not is_rune:
            raise ValueError("Unregistered rune glyph cannot be silently excluded")
        if (token.get("kind") == "rune") != is_rune:
            raise ValueError("Token kind and original rune glyph disagree")
        if is_rune:
            ordinal = len(values)
            rune_info = token.get("rune")
            if not isinstance(rune_info, dict):
                raise ValueError("Rune token is missing its original index record")
            value = rune_info.get("index")
            if type(value) is not int or not 0 <= value <= 28 or RUNES[value] != char:
                raise ValueError("Rune index must be the original glyph's 0..28 index")
            if token.get("rune_ordinal") != ordinal:
                raise ValueError("Non-contiguous original rune ordinals")
            first_in_group = pending_hard
            if first_in_group:
                group += 1
                segments.append([ordinal, ordinal])
            values.append(value)
            rune_tokens.append(token)
            groups.append(group)
            hyphens.append(int(pending_hyphen and not first_in_group))
            eligible.append(not first_in_group)
            segments[-1][1] = ordinal + 1
            pending_hard, pending_hyphen = False, False
        elif char in SOFT_SEPARATORS or (token.get("kind") == "formatting" and char.isspace()):
            if char == "-":
                pending_hyphen = True
        else:
            hard_breaks.append({"token_id": token.get("id"), "source_offset": offset,
                                "raw": char, "kind": token.get("kind"),
                                "before_rune_ordinal": len(values)})
            pending_hard = True
            pending_hyphen = False

    if "indices" in page and page["indices"] != values:
        raise ValueError("Page indices disagree with retained rune tokens")
    if "rune_count" in page and page["rune_count"] != len(values):
        raise ValueError("Page rune count disagrees with retained rune tokens")
    metadata = {key: page.get(key) for key in (
        "source", "source_sha256", "source_upstream_version", "image_path",
        "image_sha256", "version", "derived_at_utc", "extraction")}
    metadata.update(raw_sha256=raw_sha, raw_codepoints=len(raw),
                    raw_utf8_bytes=len(raw.encode("utf8")), token_count=len(tokens),
                    hard_breaks=hard_breaks, segment_count=len(segments),
                    applicability={"rune_structure": bool(values),
                                   "reason": None if values else "No GP rune tokens; rune-domain structural tests are inapplicable."},
                    parser_version="H008-structure-inputs-v1",
                    soft_separators="-.,/ and whitespace formatting tokens",
                    first_positions_excluded_from_boundary_tests=True)
    return {"page": page["page"], "page_number": page.get("page_number"),
            "indices": values, "groups": groups, "hyphen_mask": hyphens,
            "boundary_eligible": eligible, "rune_tokens": rune_tokens,
            "segments": segments, "metadata": metadata}
