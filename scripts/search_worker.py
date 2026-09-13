"""Standalone blind search worker: public stdin only, filesystem/network denied.

Frozen scorer v1: additive-smoothed training unigram log likelihood. Fixed
offsets 0..31, shifts 0..28; no skip. Exhaustive, deterministic tie ordering.
No LP plaintext, heldout text, answer, seed, or project imports.
"""
import json
import math
import sys

def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(("socket.", "subprocess.", "ctypes.")):
        raise PermissionError("blind worker denies filesystem/process/network access")

def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("Read isolation is not active")
    public = json.loads(sys.stdin.read())
    if set(public) != {"ciphertext", "training_counts", "offset_max", "shift_max", "schema"}:
        raise ValueError("Unexpected public fields")
    if public["schema"] != 1 or public["offset_max"] != 31 or public["shift_max"] != 28:
        raise ValueError("Unregistered search configuration")
    cipher, counts = public["ciphertext"], public["training_counts"]
    if not cipher or any(type(v) is not int or not 0 <= v < 29 for v in cipher):
        raise ValueError("Invalid ciphertext indices")
    if len(counts) != 29 or any(type(v) is not int or v < 0 for v in counts):
        raise ValueError("Invalid training profile")
    # Independent sieve implementation, not the generator's prime routine.
    required, bound = len(cipher)+31, max(128, (len(cipher)+31)*20)
    sieve = bytearray(b"\x01") * bound
    sieve[:2] = b"\x00\x00"
    for n in range(2, math.isqrt(bound-1)+1):
        if sieve[n]:
            for k in range(n*n, bound, n):
                sieve[k] = 0
    ps = [i for i, prime in enumerate(sieve) if prime]
    if len(ps) < required:
        raise ValueError("Prime sieve bound insufficient")
    weights = [math.log((c+1)/(sum(counts)+29)) for c in counts]
    rankings = []
    for offset in range(32):
        for shift in range(29):
            plain = [(v-ps[i+offset]+shift)%29 for i,v in enumerate(cipher)]
            score = sum(weights[v] for v in plain)
            rankings.append(dict(offset=offset, shift=shift, score=score))
    rankings.sort(key=lambda r: (-r["score"], r["offset"], r["shift"]))
    best = rankings[0]
    recovered = [(v-ps[i+best["offset"]]+best["shift"])%29 for i,v in enumerate(cipher)]
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded,
                          covered=len(rankings), selected=best, plaintext=recovered,
                          score_gap=best["score"]-rankings[1]["score"], rankings=rankings)))

if __name__ == "__main__":
    main()
