"""GP ordering is deliberately distinct from Latin rendering and prime values."""
from dataclasses import dataclass

RUNES = "ᚠᚢᚦᚩᚱᚳᚷᚹᚻᚾᛁᛄᛇᛈᛉᛋᛏᛒᛖᛗᛚᛝᛟᛞᚪᚫᚣᛡᛠ"
LATIN = tuple(tuple(x.split("/")) for x in
              "F U TH O R C/K G W H N I J EO P X S/Z T B E M L NG/ING OE D A AE Y IA/IO EA".split())

def primes(n):
    found, candidate = [], 2
    while len(found) < n:
        if all(candidate % p for p in found if p * p <= candidate):
            found.append(candidate)
        candidate += 1
    return found

GP = tuple(primes(29))

@dataclass(frozen=True)
class Rune:
    raw: str
    index: int
    latin_options: tuple[str, ...]
    prime_value: int

def rune(raw):
    i = RUNES.index(raw)  # Unknown glyphs fail, never silently normalize.
    return Rune(raw, i, LATIN[i], GP[i])

def display(index):
    choices = LATIN[index]
    return choices[0] if len(choices) == 1 else "[" + "|".join(choices) + "]"

def indices(text):
    return [RUNES.index(c) for c in text if c in RUNES]
