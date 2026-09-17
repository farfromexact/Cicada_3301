"""Coordinate mechanics only. Integer grid cells are not original rune indices."""
from collections import Counter
import re
from .clues import blocks, matrix_check
from .math_audit import phi, symmetry_checks


def ring_paths(n):
    if type(n) is not int or n < 1 or n % 2 != 1:
        raise ValueError('Positive odd grid dimension required')
    rings = []
    for lo in range(n // 2 + 1):
        hi = n - 1 - lo
        if lo == hi:
            ring = [(lo, lo)]
        else:
            ring = ([(lo, c) for c in range(lo, hi)] +
                    [(r, hi) for r in range(lo, hi)] +
                    [(hi, c) for c in range(hi, lo, -1)] +
                    [(r, lo) for r in range(hi, lo, -1)])
        rings.append(ring)
    return rings


def traversals(n):
    base = [p for ring in ring_paths(n) for p in ring]
    paths = {}
    for transpose in (False, True):
        for rotations in range(4):
            path = []
            for row, col in base:
                if transpose:
                    row, col = col, row
                for _ in range(rotations):
                    row, col = col, n - 1 - row
                path.append((row, col))
            name = f'transpose{int(transpose)}-rotate{90*rotations}'
            paths[name + '-inward'] = path
            paths[name + '-outward'] = list(reversed(path))
    return paths


def inspect_grid(matrix):
    n = len(matrix)
    if not n or any(len(row) != n for row in matrix):
        raise ValueError('Square grid required')
    paths = traversals(n)
    rings = ring_paths(n)
    flat = [v for row in matrix for v in row]
    maps = {'integer_cell': lambda x: x, 'cell_mod29': lambda x: x % 29,
            'phi_cell_mod29': lambda x: phi(x) % 29}
    rows, groups, checks = [], {}, []
    for view, mapping in maps.items():
        mapped = [mapping(x) for x in flat]
        signatures = {}
        for name, path in paths.items():
            source_indices = [r*n+c for r, c in path]
            values = [mapping(matrix[r][c]) for r, c in path]
            restored = [None] * (n*n)
            for position, value in zip(source_indices, values):
                restored[position] = value
            properties = dict(bijection=sorted(source_indices) == list(range(n*n)),
                              inverse_exact=restored == mapped,
                              scalar_map_commutes=values == [mapped[i] for i in source_indices],
                              histogram_equal=Counter(values) == Counter(mapped),
                              additive_score_equal=sum((x+1)**2 for x in values) == sum((x+1)**2 for x in mapped))
            checks.extend(properties.values())
            signatures.setdefault(tuple(values), []).append(name)
            rows.append(dict(view=view, name=name, source_coordinates=path,
                             source_flat_indices=source_indices, values=values, checks=properties))
        groups[view] = list(signatures.values())
    labelled = {tuple(r*n+c for r, c in p) for p in paths.values()}
    broken = [list(row) for row in matrix]
    broken[-1][-1] += 1
    broken_count = len({tuple(broken[r][c] for r, c in p) for p in paths.values()})
    return dict(values=matrix, symmetries=symmetry_checks(matrix),
                ring_values=[[matrix[r][c] for r, c in ring] for ring in rings],
                ring_lengths=[len(ring) for ring in rings],
                ring_sums=[sum(matrix[r][c] for r, c in ring) for ring in rings],
                row_sums=[sum(row) for row in matrix],
                column_sums=[sum(matrix[r][c] for r in range(n)) for c in range(n)],
                diagonals=[sum(matrix[i][i] for i in range(n)),sum(matrix[i][n-1-i] for i in range(n))],
                traversals=rows, equivalence_classes=groups,
                unique_sequences={key:len(value) for key, value in groups.items()},
                controls=dict(distinct_label_paths=len(labelled), broken_corner_unique_sequences=broken_count,
                              broken_corner_rotate180=symmetry_checks(broken)['rotate180']['equal']),
                exact_properties_passed=all(checks) and len(labelled)==len(paths),
                interpretation='Ring sums and aliases are deterministic descriptions; no statistical or decryption acceptance.')


def audit(root):
    first = matrix_check(root)
    path = root / 'sources/clues-v1/ibot/liber_primus/markdown/16.md'
    # Use raw first fenced transcription; never Cleaned up Plaintext.
    raw_lines = blocks(path)[0].strip().splitlines()[-5:]
    if any(not re.fullmatch(r'\d+(?:\s+\d+){4}', line) for line in raw_lines):
        raise ValueError('Expected five explicit decimal rows in first source block')
    second = [[int(v) for v in line.split()] for line in raw_lines]
    feed = (root / 'sources/feed010/user-proposal.txt').read_text(encoding='utf8')
    feed_rows = re.findall(r'(?m)^(\d+(?:&\d+){4})(?:\\\\)?[ \t]*$', feed)
    if len(feed_rows) != 5:
        raise ValueError('Expected exactly five LaTeX numeric matrix rows in feed')
    feed_matrix = [[int(v) for v in row.split('&')] for row in feed_rows]
    result = {page:inspect_grid(matrix) for page,matrix in [('LP1/05',first['values']),('LP1/16',second)]}
    return dict(status='passed' if first['status']=='passed' and feed_matrix==second and
                all(v['exact_properties_passed'] and v['ring_lengths']==[16,8,1] for v in result.values()) else 'negative',
                feed_numeric_matrix_matches_pinned_transcription=feed_matrix==second,
                grids=result, coverage=dict(known_grids=2, cells=50, coordinate_paths=32,
                                           path_view_evaluations=96, unsolved_page_candidates=0),
                cryptanalytic_conclusion='inconclusive: no hidden reading order or key established',
                source_limit='LP1/16 first fenced numeric transcription checked; original image not independently audited in this run.')
