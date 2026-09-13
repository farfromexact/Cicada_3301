"""Generator/verifier only. Never imported by the blind worker."""
import math
import random
from .runes import RUNES

def encode_text(text):
    # Fixed synthetic-only orthography: TH is one rune; others are single letters.
    # It does not purport to reconstruct LP's ambiguous English-to-rune spelling.
    letters = "F U TH O R C G W H N I J EO P X S T B E M L NG OE D A AE Y IO EA".split()
    mapping = {letter:i for i,letter in enumerate(letters)}
    text = text.upper().translate(str.maketrans({"V":"U", "K":"C", "Q":"C", "Z":"S"}))
    result, i = [], 0
    while i < len(text):
        if text[i:i+2] == "TH":
            result.append(mapping["TH"])
            i += 2
        else:
            if text[i].isalpha():
                result.append(mapping[text[i]])
            i += 1
    return result

def independent_primes(count):
    result, n = [], 2
    while len(result) < count:
        if all(n % d != 0 for d in range(2, math.isqrt(n)+1)):
            result.append(n)
        n += 1
    return result

def generate(plain, seed):
    rng = random.Random(seed)
    key = dict(offset=rng.randrange(32), shift=rng.randrange(29))
    ps = independent_primes(len(plain)+key["offset"])
    cipher = [(p+ps[i+key["offset"]]-key["shift"])%29 for i,p in enumerate(plain)]
    return cipher, dict(seed=seed, key=key, plaintext=plain)

def verify(answer, candidate, cipher):
    key_match = all(candidate["selected"].get(k) == v for k,v in answer["key"].items())
    exact = candidate["plaintext"] == answer["plaintext"]
    key = candidate["selected"]
    ps = independent_primes(len(cipher)+key["offset"])
    reencrypted = [(p+ps[i+key["offset"]]-key["shift"])%29 for i,p in enumerate(candidate["plaintext"])]
    roundtrip = reencrypted == cipher
    return dict(status="passed" if exact and key_match and roundtrip else "negative",
                exact_plaintext=exact, exact_key=key_match, roundtrip=roundtrip)
