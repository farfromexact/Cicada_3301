"""Exact source-derived checks; no prose generation or language scoring."""
import re
from .runes import RUNES, GP, indices
from .model import tokenize
from .cipher import transform
from .reference import reference_indices

BASE = "sources/clues-v1/ibot/"

def blocks(path):
    return re.findall(r"```\n(.*?)```", path.read_text(encoding="utf8"), re.S)

def warning_check(root):
    master_path = root / "sources/iddqd/liber-primus__transcription--master/liber-primus__transcription--master.txt"
    master = master_path.read_text(encoding="utf8")
    start = master.index("\nᚱ-")+1
    end = master.index("%",start)
    raw = master[start:end]
    md = root / BASE / "liber_primus/markdown/01.md"
    source_agreement = indices(raw) == indices(blocks(md)[0])
    # Coarse line regions in 2400x3600 original, with separate oversized initial.
    regions = {str(i+1):[590,650+i*217,1810,810+i*217] for i in range(9)}
    image = BASE+"liber_primus/01.jpg"
    tokens = tokenize(raw,"LP1/01",image,regions)
    tokens[0]["image"] = dict(path=image,bbox=[590,650,775,1235],precision="glyph_region_manual")
    decoded = transform(tokens,mode="atbash")
    expected = reference_indices(md,cipher_block=0)
    actual = indices(decoded["raw"])
    inverse = transform(tokenize(decoded["raw"],"LP1/01",image,regions),mode="atbash")["raw"]
    negative = transform(tokens,mode="identity")
    mismatches = [i for i,(a,b) in enumerate(zip(indices(negative["raw"]),expected)) if a != b]
    return dict(page="LP1/01",raw=raw,source=master_path.relative_to(root).as_posix(),
        extraction=dict(start_codepoint=start,end_codepoint=end),tokens=tokens,decoded=decoded,
        expected_indices=expected,rune_count=len(actual),cross_source_equal=source_agreement,
        exact_runes=actual==expected,roundtrip_exact=inverse==raw,
        negative_control=dict(mode="identity",status="negative" if mismatches else "passed",mismatches=mismatches,output=negative),
        status="passed" if source_agreement and actual==expected and inverse==raw and mismatches else "negative")

def matrix_check(root):
    md_path = root / BASE / "liber_primus/markdown/05.md"
    md = md_path.read_text(encoding="utf8")
    raw_block = blocks(md_path)[0]
    rows = raw_block.strip().splitlines()[-5:]
    raw_cells = [line.split() for line in rows]
    if any(len(row)!=5 for row in raw_cells):
        raise ValueError("Expected a 5 by 5 matrix")
    ref = re.search(r"### Magic Square\s+```\n(.*?)```",md,re.S).group(1)
    expected = [[int(v) for v in line.split()] for line in ref.strip().splitlines()]
    cells = []
    values = []
    xbounds = [580,835,1080,1340,1590,1820]
    for row, raw_row in enumerate(raw_cells):
        out = []
        for col, text in enumerate(raw_row):
            if text.isascii() and text.isdigit():
                value, runes = int(text), []
            else:
                if any(c not in RUNES for c in text):
                    raise ValueError("Unknown matrix cell character")
                runes = indices(text)
                value = sum(GP[i] for i in runes)
            cells.append(dict(row=row,column=col,raw=text,indices=runes,prime_values=[GP[i] for i in runes],
                              value=value,expected=expected[row][col],equal=value==expected[row][col],
                              source=md_path.relative_to(root).as_posix(),locator=f"first fenced block, matrix row {row+1}, cell {col+1}",
                              image=dict(path=BASE+"liber_primus/05.jpg",bbox=[xbounds[col],2190+row*126,xbounds[col+1],2330+row*126],precision="cell_region_manual")))
            out.append(value)
        values.append(out)
    return dict(page="LP1/05",scope="matrix only; page prose is source-reported",cells=cells,values=values,expected=expected,
                row_sums=[sum(row) for row in values],column_sums=[sum(values[r][c] for r in range(5)) for c in range(5)],
                diagonals=[sum(values[i][i] for i in range(5)),sum(values[i][4-i] for i in range(5))],
                status="passed" if values==expected else "negative")
