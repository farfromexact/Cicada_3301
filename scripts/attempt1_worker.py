"""H006-v1 fixed prime-clock transforms. Public stdin only; no answer access."""
import json
import math
import sys

METHODS = ("page", "line", "paragraph", "corpus")


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(("socket.", "subprocess.", "ctypes.")):
        raise PermissionError("H006 worker denies file/process/network access")


def prime_sieve(count):
    bound = max(128, count * 20)
    sieve = bytearray(b"\x01") * bound
    sieve[:2] = b"\x00\x00"
    for p in range(2, math.isqrt(bound - 1) + 1):
        if sieve[p]:
            sieve[p*p:bound:p] = b"\x00" * len(range(p*p, bound, p))
    values = [n for n, flag in enumerate(sieve) if flag]
    if len(values) < count:
        raise ValueError("Prime sieve exhausted")
    return values[:count]


def run(public):
    if set(public) != {"schema", "hypothesis", "training_counts", "pages"}:
        raise ValueError("Unexpected public fields; no answers, keys or seeds allowed")
    if public["schema"] != 1 or public["hypothesis"] != "H006-v1":
        raise ValueError("Unknown experiment")
    counts = public["training_counts"]
    if len(counts) != 29 or any(type(x) is not int or x < 0 for x in counts) or not sum(counts):
        raise ValueError("Invalid fixed training counts")
    weights = [math.log((x + 1) / (sum(counts) + 29)) for x in counts]
    pages = public["pages"]
    seen = set()
    for page in pages:
        if set(page) != {"page", "cipher", "line_starts", "paragraph_starts"} or page["page"] in seen:
            raise ValueError("Invalid page fields or duplicate page")
        seen.add(page["page"])
        n = len(page["cipher"])
        if not n or any(type(c) is not int or not 0 <= c < 29 for c in page["cipher"]):
            raise ValueError("Invalid ciphertext indices")
        for name in ("line_starts", "paragraph_starts"):
            starts = page[name]
            if starts != sorted(set(starts)) or not starts or starts[0] != 0 or any(type(i) is not int or not 0 <= i < n for i in starts):
                raise ValueError("Invalid boundary ordinals")
    ps = prime_sieve(sum(len(page["cipher"]) for page in pages))
    result, offset = [], 0
    for page in pages:
        cipher = page["cipher"]
        unique = {}
        for method in METHODS:
            starts = set(page.get(method + "_starts", [0]))
            origin = 0
            delta = []
            for i in range(len(cipher)):
                if method in {"line", "paragraph"} and i in starts:
                    origin = i
                clock = offset + i if method == "corpus" else i - origin
                delta.append((ps[clock] - 1) % 29)
            signature = tuple(delta)
            if signature in unique:
                unique[signature]["methods"].append(method)
                continue
            plain = [(c - d) % 29 for c, d in zip(cipher, delta)]
            row = dict(page=page["page"], methods=[method], delta=delta,
                       plaintext=plain, log_likelihood=math.fsum(weights[p] for p in plain))
            unique[signature] = row
            result.append(row)
        offset += len(cipher)
    return dict(status="completed", raw_branch_evaluations=4*len(pages),
                unique_evaluations=len(result), rune_count=offset, results=result)


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        protected = True
    else:
        raise RuntimeError("Read guard failed")
    result = run(json.loads(sys.stdin.read()))
    result["read_guard_probe_passed"] = protected
    print(json.dumps(result))


if __name__ == "__main__":
    main()
