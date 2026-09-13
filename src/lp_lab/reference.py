"""Independent expectation from source Latin + input word rune counts.

Never calls the cipher. Ambiguous Latin segmentation must fail instead of choosing
the segmentation that happens to agree with a decryption.
"""
from functools import lru_cache
from pathlib import Path
import re
from .runes import RUNES, LATIN

def segment_word(word, rune_count):
    # Bracket alternatives in the source represent one rune, not several letters.
    @lru_cache(None)
    def visit(pos, left):
        if left == 0:
            return [()] if pos == len(word) else []
        answers = []
        for index, choices in enumerate(LATIN):
            spellings = [choices[0]] if len(choices) == 1 else ["["+"|".join(choices)+"]"]
            for spelling in spellings:
                if word.startswith(spelling, pos):
                    answers += [(index,)+rest for rest in visit(pos+len(spelling), left-1)]
        return answers
    matches = visit(0, rune_count)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one reference segmentation: {word}, {rune_count}, {len(matches)}")
    return list(matches[0])

def reference_indices(md_path):
    md = Path(md_path).read_text(encoding="utf8")
    blocks = re.findall(r"```\n(.*?)```", md, re.S)
    ciphertext_words = blocks[1].split()
    plaintext = re.search(r"### Plaintext\s+```\n(.*?)```", md, re.S).group(1)
    plain_words = plaintext.split()
    if len(ciphertext_words) != len(plain_words):
        raise ValueError("Reference word counts differ")
    result = []
    for cipher_word, plain_word in zip(ciphertext_words, plain_words):
        count = sum(c in RUNES for c in cipher_word)
        if count:
            result.extend(segment_word(plain_word, count))
        elif cipher_word != plain_word:
            raise ValueError("Literal block differs")
    return result
