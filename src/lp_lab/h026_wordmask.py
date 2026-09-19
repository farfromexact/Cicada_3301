"""H026 public word fingerprints; no source, plaintext or generation seed I/O."""
from collections import Counter
import random
from .runes import RUNES

CONTROL_SEED = 330119260

def blocks(raw):
    result, current, offsets = [], [], []
    for i, c in enumerate(raw):
        if c in RUNES:
            current.append(RUNES.index(c)); offsets.append(i)
        elif c in '/ \r\n\t':
            continue
        else:
            if 0x16A0 <= ord(c) <= 0x16FF:
                raise ValueError('unregistered rune')
            if current:
                result.append(dict(values=current,offsets=offsets))
                current, offsets = [], []
    if current: result.append(dict(values=current,offsets=offsets))
    return result

def fingerprint(word):
    return (len(word),tuple((x-word[0])%29 for x in word))

def collisions(words):
    counts=Counter(fingerprint(w) for w in words if len(w)>=3)
    return sum(n*(n-1)//2 for n in counts.values())

def control_words(words, job_index, replicate):
    rng=random.Random(CONTROL_SEED+job_index*1000+replicate)
    result=[]
    for w in words:
        a=list(w); rng.shuffle(a); result.append(a)
    return result

def analyze(words,job_index):
    observed=collisions(words)
    controls=[collisions(control_words(words,job_index,r)) for r in range(99)]
    return dict(observed=observed,controls=controls,p=(1+sum(x>=observed for x in controls))/100,
                words=len(words),runes=sum(map(len,words)))
