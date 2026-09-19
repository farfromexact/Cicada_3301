"""H027 blind training-only pair decoder. No project imports or private inputs."""
import json
import math
import sys

HYPOTHESIS = "H027-adjacent-reused-stream-v1"
M = 29


def guard(event, args):
    if event in {"open", "os.listdir", "os.scandir", "os.system"} or event.startswith(("socket.", "subprocess.", "ctypes.")):
        raise PermissionError("H027 worker denies filesystem/process/network access")


def validate_public(public):
    if set(public) != {"schema", "hypothesis", "unigram_counts", "bigram_counts", "jobs"}:
        raise ValueError("H027 unexpected public fields; private material forbidden")
    if public["schema"] != 1 or public["hypothesis"] != HYPOTHESIS:
        raise ValueError("Wrong H027 schema")
    u, b = public["unigram_counts"], public["bigram_counts"]
    if len(u) != M or len(b) != M or any(len(row) != M for row in b):
        raise ValueError("Wrong H027 model dimensions")
    if any(type(v) is not int or v < 0 for v in u + [v for row in b for v in row]):
        raise ValueError("Invalid H027 training counts")
    jobs = public["jobs"]
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 119:
        raise ValueError("Invalid H027 job count")
    ids = set()
    for job in jobs:
        if set(job) != {"id", "a", "b"} or not isinstance(job["id"], str) or job["id"] in ids:
            raise ValueError("Invalid H027 job fields/id")
        ids.add(job["id"])
        if not isinstance(job["a"], list) or not isinstance(job["b"], list) or len(job["a"]) != len(job["b"]) or not 30 <= len(job["a"]) <= 1000:
            raise ValueError("Invalid H027 lengths")
        if any(type(v) is not int or not 0 <= v < M for v in job["a"] + job["b"]):
            raise ValueError("Invalid H027 rune value")
    return jobs


def model_from_counts(unigrams, bigrams):
    pi = [(v + 1) / (sum(unigrams) + M) for v in unigrams]
    trans = [[(v + 1) / (sum(row) + M) for v in row] for row in bigrams]
    total = sum(map(sum, bigrams)) + M * M
    joint = [[(v + 1) / total for v in row] for row in bigrams]
    dif_pi = [sum(pi[x] * pi[(x - d) % M] for x in range(M)) for d in range(M)]
    dif_joint = [[sum(joint[x][y] * joint[(x - a) % M][(y - b) % M] for x in range(M) for y in range(M)) for b in range(M)] for a in range(M)]
    dif_trans = [[v / sum(row) for v in row] for row in dif_joint]
    return dict(log_pi=list(map(math.log, pi)), log_t=[list(map(math.log, row)) for row in trans], log_dpi=list(map(math.log, dif_pi)), log_dt=[list(map(math.log, row)) for row in dif_trans])


def viterbi(difference, model, previous=None):
    lp, lt = model["log_pi"], model["log_t"]
    d0 = difference[0]
    values = [(lp[a] + lp[(a - d0) % M]) if previous is None else lt[previous[0]][a] + lt[previous[1]][(a - d0) % M] for a in range(M)]
    history = []
    for before, current in zip(difference, difference[1:]):
        next_values, pointers = [], []
        for a in range(M):
            b = (a - current) % M
            best_p, best = 0, -math.inf
            for prev in range(M):
                candidate = values[prev] + lt[prev][a] + lt[(prev - before) % M][b]
                if candidate > best:
                    best_p, best = prev, candidate
            next_values.append(best)
            pointers.append(best_p)
        history.append(pointers)
        values = next_values
    last = max(range(M), key=values.__getitem__)
    optimum = values[last]
    a_path = [last]
    for pointers in reversed(history):
        a_path.append(pointers[a_path[-1]])
    a_path.reverse()
    b_path = [(a - d) % M for a, d in zip(a_path, difference)]
    return a_path, b_path, optimum


def difference_scores(d, split, model):
    terms = [model["log_dpi"][d[0]] + math.log(M)]
    terms.extend(model["log_dt"][a][b] + math.log(M) for a, b in zip(d, d[1:]))
    return [sum(terms[:split]), sum(terms[split:])]


def run_job(job, model):
    d = [(a - b) % M for a, b in zip(job["a"], job["b"])]
    split = 2 * len(d) // 3
    a0, b0, score0 = viterbi(d[:split], model)
    a1, b1, score1 = viterbi(d[split:], model, (a0[-1], b0[-1]))
    a, b = a0 + a1, b0 + b1
    key_a = [(c - p) % M for c, p in zip(job["a"], a)]
    key_b = [(c - p) % M for c, p in zip(job["b"], b)]
    return dict(id=job["id"], difference=d, split=split, a=a, b=b, key_a=key_a, key_b=key_b, viterbi_scores=[score0, score1], log_bf=difference_scores(d, split, model))


def main():
    sys.addaudithook(guard)
    try:
        open("__forbidden_probe__", "rb")
    except PermissionError:
        guarded = True
    else:
        raise RuntimeError("H027 guard not active")
    public = json.loads(sys.stdin.read())
    jobs = validate_public(public)
    model = model_from_counts(public["unigram_counts"], public["bigram_counts"])
    print(json.dumps(dict(status="completed", read_guard_probe_passed=guarded, jobs=[run_job(job, model) for job in jobs]), separators=(",", ":")))


if __name__ == "__main__":
    main()
