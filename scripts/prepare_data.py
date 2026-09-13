"""Deterministic derivation from pinned originals; no downloaded code execution."""
from pathlib import Path
import hashlib
import json
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.runes import RUNES, indices
from lp_lab.model import tokenize

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+"\n", encoding="utf8")

def main():
    master_path = ROOT / "sources/iddqd/liber-primus__transcription--master/liber-primus__transcription--master.txt"
    master = master_path.read_text(encoding="utf8")
    # Exact trailing page segments, including their source formatting and end markers.
    pages = master.split("%")
    records = []
    for page, section_index, ibot_page in [(56, -3, 73), (57, -2, 74)]:
        raw = pages[section_index]
        md = (ROOT / f"sources/ibot/liber_primus/markdown/{ibot_page}.md").read_text(encoding="utf8")
        blocks = re.findall(r"```\n(.*?)```", md, re.S)
        source_runes = indices(blocks[0])
        if indices(raw) != source_runes:
            raise ValueError(f"Cross-source rune disagreement on {page}")
        # Measured containing regions on 2400x3600 originals; intentionally coarse.
        if page == 56:
            boxes = [[595,660,1785,1175],[755,850,1790,1000],[755,1040,1110,1180],
                     [595,1225,1810,1325],[595,1330,1810,1435],[595,1440,1810,1545],
                     [595,1550,1810,1655],[595,1660,1810,1765],
                     [590,1870,1800,2030],[590,2060,1610,2220]]
            # Upstream uses codepoint index 202 in a flattened string, NOT rune index 202.
            single = blocks[1].strip()
            assert single[202] == "ᚠ"
            skip = [sum(c in RUNES for c in single[:202])]
        else:
            boxes = [[590,900,1800,1210],[870,1090,1800,1240],
                     [590,1270,1800,1530],[870,1520,1770,1670],[590,1700,1730,1860]]
            skip = []
        regions = {str(i+1): box for i, box in enumerate(boxes)}
        image_path = f"sources/iddqd/liber-primus__images--unsolved/{page}.jpg"
        tokens = tokenize(raw, f"LP2/{page}", image_path, regions)
        # Oversized initial rune is a drop cap; improve that one glyph's region explicitly.
        first = next(t for t in tokens if t["kind"] == "rune")
        first["image"] = dict(path=image_path, bbox=[595,660,755,1175] if page == 56 else [595,900,890,1530],
                              precision="glyph_region_manual")
        record = dict(schema=1, page=f"LP2/{page}", source=master_path.relative_to(ROOT).as_posix(),
                      source_sha256=hashlib.sha256(master_path.read_bytes()).hexdigest(),
                      extraction=dict(method="split literal percent", segment_index=section_index),
                      raw=raw, image_path=image_path, image_size=[2400,3600], regions=regions,
                      tokens=tokens, parameters=dict(mode="prime" if page == 56 else "identity", offset=0, shift=1, skip=skip),
                      cross_source=dict(path=f"sources/ibot/liber_primus/markdown/{ibot_page}.md",
                                        rune_sequence_equal=True, count=len(source_runes),
                                        independence="different repository; common transcription ancestry not excluded"))
        write(ROOT / f"data/pages/lp2_{page}.json", record)
        records.append(dict(page=page, runes=len(source_runes), skip=skip))
    print(json.dumps(records))

if __name__ == "__main__":
    main()
