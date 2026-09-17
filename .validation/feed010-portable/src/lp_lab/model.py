from dataclasses import asdict
from .runes import RUNES, rune

DELIMITERS = {"-": "word", ",": "three_dot", ".": "clause",
              "&": "paragraph", "$": "segment", "§": "chapter", "/": "line", "%": "page"}

def tokenize(raw, page_id, image_path, regions):
    """Lossless codepoint stream; / records image lines, newlines are file formatting.

    bbox is a containing line region, NOT an invented per-glyph bounding box.
    A future image audit can supply glyph boxes without changing token identities.
    """
    result, line, paragraph, ordinal, column = [], 1, 1, 0, 0
    for offset, char in enumerate(raw):
        is_rune = char in RUNES
        if 0x16A0 <= ord(char) <= 0x16FF and not is_rune:
            raise ValueError(f"Unregistered rune {char!r} at {offset}; annotate before use")
        kind = "rune" if is_rune else DELIMITERS.get(char, "formatting" if char.isspace() else "literal")
        region = regions.get(str(line))
        token = dict(id=f"{page_id}:{offset}", raw=char, kind=kind, source_offset=offset,
                     page=page_id, line=line, paragraph=paragraph, column=column,
                     image=dict(path=image_path, bbox=region, precision="line_region" if region else "unlocated"),
                     ambiguity=[], rune=None, rune_ordinal=None)
        if is_rune:
            token["rune"] = asdict(rune(char))
            token["rune_ordinal"] = ordinal
            ordinal += 1
        elif char == ";":
            token["ambiguity"] = [dict(type="delimiter", status="unresolved",
                                       note="Master uses semicolon, absent from its legend; raw retained")]
        result.append(token)
        if char == "/":
            line += 1
            column = 0
        elif char == "&":
            paragraph += 1
        elif not char.isspace():
            column += 1
    return result
