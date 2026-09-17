"""H008 structural measurements and bounded conditional randomization.

Inputs contain only rune indices and literal-layout annotations.  There is no
language model, candidate key, plaintext reference, or corpus file access here.
Family A tests lag equality, B literal hyphen association, C cross-page 4-grams.
"""
from collections import Counter
import time

import numpy as np


LAGS = tuple(range(1, 30))
FAMILY_ALPHA = 0.01 / 3
TIE_TOLERANCE = 1e-12


class _Layout:
    def __init__(self, pages):
        if not pages:
            raise ValueError("At least one rune-bearing page is required")
        self.sequences = []
        self.lag_pairs = []
        self.window_starts = []
        self.boundaries = []
        self.segments = []
        for page in pages:
            values = np.asarray(page["indices"])
            if values.ndim != 1 or not len(values) or values.dtype.kind not in "iu":
                raise ValueError("Each page must have a nonempty integer rune sequence")
            if np.any((values < 0) | (values >= 29)):
                raise ValueError("Rune indices must be in 0..28")
            values = values.astype(np.int64, copy=True)
            n = len(values)
            groups = np.asarray(page["groups"])
            if groups.shape != (n,) or groups.dtype.kind not in "iu":
                raise ValueError("groups must provide one integer group per rune")
            # Groups denote contiguous prose regions. Reusing a group after an
            # intervening group would silently admit pairs across hard breaks.
            runs = groups[np.r_[True, groups[1:] != groups[:-1]]]
            if len(set(runs.tolist())) != len(runs):
                raise ValueError("A prose group cannot recur after a hard break")
            self.sequences.append(values)
            pairs = []
            for lag in LAGS:
                starts = np.arange(max(0, n - lag), dtype=np.int64)
                starts = starts[groups[starts] == groups[starts + lag]]
                pairs.append((starts, starts + lag))
            self.lag_pairs.append(pairs)
            starts = np.arange(max(0, n - 3), dtype=np.int64)
            self.window_starts.append(starts[groups[starts] == groups[starts + 3]])
            hyphens = np.asarray(page["hyphen_mask"], dtype=bool)
            eligible = np.asarray(page["boundary_eligible"], dtype=bool)
            if hyphens.shape != (n,) or eligible.shape != (n,):
                raise ValueError("Boundary masks must have one entry per rune")
            positions = np.flatnonzero(eligible)
            labels = hyphens[positions].astype(np.int64)
            self.boundaries.append((positions, labels))
            segments = []
            previous_end = 0
            for segment in page["segments"]:
                if len(segment) != 2:
                    raise ValueError("Segments must be [start, end) pairs")
                start, end = segment
                if type(start) is not int or type(end) is not int:
                    raise ValueError("Segment offsets must be integers")
                if not 0 <= start < end <= n or start < previous_end:
                    raise ValueError("Segments must be ordered, nonoverlapping, and in range")
                if groups[start] != groups[end - 1]:
                    raise ValueError("A prose segment cannot cross a hard group break")
                segments.append((start, end))
                previous_end = end
            self.segments.append(segments)

    def validate_sequences(self, sequences):
        if len(sequences) != len(self.sequences):
            raise ValueError("Replacement sequences must retain every page")
        result = []
        for values, original in zip(sequences, self.sequences):
            values = np.asarray(values)
            if values.shape != original.shape or values.dtype.kind not in "iu":
                raise ValueError("Replacement sequence shape or integer type is invalid")
            if np.any((values < 0) | (values >= 29)):
                raise ValueError("Replacement rune indices must be in 0..28")
            result.append(values.astype(np.int64, copy=False))
        return result


def _association(sequence, boundary):
    positions, labels = boundary
    if not len(positions) or labels.min() == labels.max():
        return 0.0
    observed = np.bincount(sequence[positions] * 2 + labels,
                           minlength=58).reshape(29, 2).astype(float)
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / len(positions)
    positive = observed > 0
    return max(0.0, float(2 * np.sum(observed[positive] *
                                   np.log(observed[positive] / expected[positive]))))


def _metrics(layout, sequences, families="ABC"):
    lag_counts = np.zeros(len(sequences) * 29, dtype=np.int64)
    boundary_statistics = np.zeros(len(sequences), dtype=float)
    prior_windows = Counter()
    cross_page_pairs = 0
    for page_index, sequence in enumerate(sequences):
        if "A" in families:
            for offset, (left, right) in enumerate(layout.lag_pairs[page_index]):
                lag_counts[page_index * 29 + offset] = np.count_nonzero(sequence[left] == sequence[right])
        if "B" in families:
            boundary_statistics[page_index] = _association(sequence, layout.boundaries[page_index])
        if "C" in families:
            starts = layout.window_starts[page_index]
            # Base-29 packing is injective for exactly four indices; no GP prime
            # conversion, hash collision, or delimiter normalization is involved.
            packed = (((sequence[starts] * 29 + sequence[starts + 1]) * 29 +
                       sequence[starts + 2]) * 29 + sequence[starts + 3])
            words, counts = np.unique(packed, return_counts=True)
            for word, count in zip(words.tolist(), counts.tolist()):
                cross_page_pairs += prior_windows[word] * count
                prior_windows[word] += count
    return lag_counts, boundary_statistics, int(cross_page_pairs)


def metrics(pages, sequences=None):
    """Return (A page-major lag counts, B per-page G statistics, C pair count).

    Soft delimiters do not consume an index. Hard prose groups bound A/C pairs
    and windows. C counts different-page occurrence pairs, including duplicate
    occurrences on either page. B uses only explicitly eligible literal gaps.
    """
    layout = _Layout(pages)
    selected = layout.sequences if sequences is None else layout.validate_sequences(sequences)
    return _metrics(layout, selected)


def _max_t(observed, null, completed):
    rows = np.vstack((observed[np.newaxis, :], null))
    mean = rows.mean(axis=0)
    std = rows.std(axis=0, ddof=0)
    discriminating = (np.ptp(rows, axis=0) > 0) & (std > 0)
    std[~discriminating] = 0.0
    z = np.zeros_like(rows, dtype=float)
    z[:, discriminating] = ((rows[:, discriminating] - mean[discriminating]) /
                            std[discriminating])
    maxima = (z[1:, discriminating].max(axis=1) if np.any(discriminating)
              else np.zeros(len(null), dtype=float))
    p = np.ones(len(observed), dtype=float)
    for index in np.flatnonzero(discriminating):
        p[index] = (1 + np.count_nonzero(maxima >= z[0, index] - TIE_TOLERANCE)) / (len(null) + 1)
    return dict(observed=observed.copy(), null=null.copy(), mean=mean, std=std,
                discriminating=discriminating, observed_z=z[0], null_z=z[1:],
                control_max_z=maxima, p_adjusted=p,
                lead=(p <= FAMILY_ALPHA) & discriminating & completed)


def randomized_scan(pages, permutations=999, seed=33010804, timeout_seconds=180,
                    progress_callback=None):
    """Run the frozen three-family scan and retain every completed control.

    A/C share each within-page full permutation. B uses a separate RNG stream
    and independent circular rotations of each supplied prose segment. Layout
    masks stay fixed. Symmetric studentization includes observation and all
    controls. Family-level maxT plus the three-family alpha controls multiplicity.

    Returns numpy arrays suitable for lossless NPZ persistence. On timeout,
    p-values describe completed controls only, and all lead flags are disabled.
    The public seed generates null randomizations, never a hidden answer/key.
    """
    if type(permutations) is not int or permutations < 1:
        raise ValueError("permutations must be a positive integer")
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be nonnegative")
    started = time.monotonic()
    layout = _Layout(pages)
    observed_a, observed_b, observed_c = _metrics(layout, layout.sequences)
    null_a = np.empty((permutations, len(observed_a)), dtype=np.int64)
    null_b = np.empty((permutations, len(observed_b)), dtype=float)
    null_c = np.empty(permutations, dtype=np.int64)
    random_states = np.random.SeedSequence(seed).spawn(2)
    permutation_rng, rotation_rng = [np.random.Generator(np.random.PCG64(state))
                                    for state in random_states]
    count = 0
    while count < permutations:
        if time.monotonic() - started >= timeout_seconds:
            break
        permuted = [permutation_rng.permutation(sequence) for sequence in layout.sequences]
        a, _, c = _metrics(layout, permuted, families="AC")
        rotated = []
        for sequence, segments in zip(layout.sequences, layout.segments):
            copied = sequence.copy()
            for start, end in segments:
                copied[start:end] = np.roll(sequence[start:end], int(rotation_rng.integers(end - start)))
            rotated.append(copied)
        _, b, _ = _metrics(layout, rotated, families="B")
        null_a[count], null_b[count], null_c[count] = a, b, c
        count += 1
        if progress_callback is not None:
            progress_callback(dict(completed_control_replicates=count,
                                   elapsed_seconds=time.monotonic() - started))
    completed = count == permutations
    null_a, null_b, null_c = null_a[:count], null_b[:count], null_c[:count]
    c_rows = np.r_[observed_c, null_c]
    c_p = (1 + np.count_nonzero(null_c >= observed_c)) / (count + 1)
    c_discriminating = bool(np.ptp(c_rows) > 0)
    families = dict(A=_max_t(observed_a, null_a, completed),
                    B=_max_t(observed_b, null_b, completed),
                    C=dict(observed=observed_c, null=null_c.copy(),
                           mean=float(c_rows.mean()), std=float(c_rows.std(ddof=0)),
                           discriminating=c_discriminating, p_adjusted=float(c_p),
                           lead=bool(completed and c_discriminating and c_p <= FAMILY_ALPHA)))
    return dict(status="completed" if completed else "timeout",
                requested_control_replicates=permutations,
                completed_control_replicates=count, elapsed_seconds=time.monotonic() - started,
                seed=seed, rng="numpy.Generator(PCG64), SeedSequence.spawn(2): A/C then B",
                family_alpha=FAMILY_ALPHA, tie_tolerance=TIE_TOLERANCE,
                families=families)
