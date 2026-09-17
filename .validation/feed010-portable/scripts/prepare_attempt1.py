"""Freeze a lossless LP2/0..55 corpus from reviewed, pinned local source bytes.

This is data preparation only. It never executes upstream code or candidate
cryptanalysis and refuses to overwrite any output from an earlier preparation.
"""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lp_lab.model import tokenize
from lp_lab.runes import RUNES

VERSION = "attempt1-corpus-v1"
UPSTREAM = "0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07"
MASTER = "sources/iddqd/liber-primus__transcription--master/liber-primus__transcription--master.txt"
CHECKOUT_MASTER = "liber-primus__transcription--master/liber-primus__transcription--master.txt"
CORPUS = "data/attempt1-corpus-v1.json"
MANIFEST = "sources/attempt1-manifest.json"
IMAGE_DIR = "sources/attempt1/images"


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def write_exclusive(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf8")


def git_read(*args):
    result = subprocess.run(
        ["git", "-C", str(ROOT / "github/iddqd"), *args],
        capture_output=True, check=True, encoding="utf8",
    )
    return result.stdout.strip()


def main():
    for target in (CORPUS, MANIFEST, "sources/attempt1"):
        if (ROOT / target).exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {target}")
    acquired = dt.datetime.now(dt.timezone.utc).isoformat()
    head = git_read("rev-parse", "HEAD")
    if head != UPSTREAM:
        raise ValueError(f"Unexpected local iddqd version: {head}")
    tree = git_read("ls-tree", "-r", UPSTREAM, "--", CHECKOUT_MASTER,
                    "liber-primus__images--unsolved", "liber-primus__images--full")
    blobs = {}
    for row in tree.splitlines():
        descriptor, name = row.split("\t", 1)
        mode, kind, object_id = descriptor.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Unexpected upstream entry: {row}")
        blobs[name] = object_id

    def verify_blob(name, payload):
        actual = hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()
        if actual != blobs.get(name):
            raise ValueError(f"Local bytes differ from pinned upstream Git blob: {name}")

    master_bytes = (ROOT / MASTER).read_bytes()
    expected_source = next(e for e in json.loads((ROOT / "sources/manifest.json").read_text(encoding="utf8"))["entries"]
                           if e["path"] == MASTER)
    if digest(master_bytes) != expected_source["sha256"]:
        raise ValueError("Pinned master source SHA-256 mismatch")
    checkout_bytes = (ROOT / "github/iddqd" / CHECKOUT_MASTER).read_bytes()
    if checkout_bytes != master_bytes:
        raise ValueError("Pinned master and checkout byte streams differ")
    # Git checkout CRLF conversion is explicit. Preserve the checked-out source
    # bytes below, but compare the Git blob in its repository LF representation.
    verify_blob(CHECKOUT_MASTER, checkout_bytes.replace(b"\r\n", b"\n"))
    master = master_bytes.decode("utf8", errors="strict")
    sections = master.split("%")
    if len(sections) != 75 or sections[-1].strip() != "§":
        raise ValueError("Expected legend + 15 LP1 text pages + 58 LP2 pages + trailing chapter marker")
    lp2 = sections[-59:-1]
    if len(lp2) != 58 or lp2 != sections[16:74]:
        raise ValueError("LP2 page boundary mapping is inconsistent")
    known_tail = []
    for page_number in (56, 57):
        known = json.loads((ROOT / f"data/pages/lp2_{page_number}.json").read_text(encoding="utf8"))
        # Earlier derived pages used universal-newline reads. Compare under that
        # documented representation without normalizing this new corpus's raw.
        if lp2[page_number].replace("\r\n", "\n") != known["raw"]:
            raise ValueError(f"LP2/{page_number} tail differs from pinned known-page extraction")
        known_tail.append({"page": f"LP2/{page_number}", "raw_equal_after_explicit_crlf_to_lf": True,
                           "known_record_sha256": digest((ROOT / f"data/pages/lp2_{page_number}.json").read_bytes())})

    images = {}
    for page_number in range(58):
        path = f"liber-primus__images--unsolved/{page_number}.jpg"
        full = f"liber-primus__images--full/{page_number + 17:02}.jpg"
        payload = (ROOT / "github/iddqd" / path).read_bytes()
        verify_blob(path, payload)
        if payload != (ROOT / "github/iddqd" / full).read_bytes():
            raise ValueError(f"Full/LP2 image numbering mismatch at LP2/{page_number}")
        verify_blob(full, payload)
        images[page_number] = payload

    starts = []
    cursor = 0
    for raw in sections:
        starts.append(cursor)
        cursor += len(raw) + 1
    entries, pages = [], []
    for page_number in range(56):
        segment_index = page_number + 16
        raw = lp2[page_number]
        source_start = starts[segment_index]
        source_byte_start = len(master[:source_start].encode("utf8"))
        if master[source_start:source_start + len(raw)] != raw:
            raise ValueError("Source span does not reproduce raw page")
        image_path = f"{IMAGE_DIR}/{page_number}.jpg"
        upstream_path = f"liber-primus__images--unsolved/{page_number}.jpg"
        tokens = tokenize(raw, f"LP2/{page_number}", image_path, {})
        byte_cursor = source_byte_start
        for token in tokens:
            token["source_global_offset"] = source_start + token["source_offset"]
            token["source_global_byte_offset"] = byte_cursor
            byte_cursor += len(token["raw"].encode("utf8"))
        if "".join(token["raw"] for token in tokens) != raw:
            raise ValueError("Tokenizer is not lossless")
        rune_tokens = [token for token in tokens if token["kind"] == "rune"]
        rune_count = len(rune_tokens)
        if [t["rune_ordinal"] for t in rune_tokens] != list(range(rune_count)):
            raise ValueError("Non-contiguous rune ordinals")
        limitations = ["Unsolved-page transcription has not received independent per-glyph image verification.",
                       "Image locations are unlocated; page image and textual line/paragraph boundaries are retained.",
                       "Separator meanings come from the source legend, not independent cryptographic validation."]
        if page_number in (49, 50, 51):
            limitations.append("Alphanumeric grid is retained as literals; it is not silently decoded or treated as GP rune indices.")
        if page_number == 50:
            applicability = {"rune_sequence_analysis": False,
                             "exclusion_reason": "LP2/50 has 0 GP rune tokens and an alphanumeric grid; rune-domain hypotheses do not apply."}
        else:
            applicability = {"rune_sequence_analysis": True, "exclusion_reason": None}
        pages.append({
            "page": f"LP2/{page_number}", "page_number": page_number,
            "raw": raw, "raw_sha256": digest(raw.encode("utf8")), "tokens": tokens,
            "rune_count": rune_count, "indices": [t["rune"]["index"] for t in rune_tokens],
            "source": MASTER, "source_sha256": expected_source["sha256"],
            "source_upstream_version": UPSTREAM, "derived_at_utc": acquired, "version": VERSION,
            "extraction": {"method": "split literal percent; LP2 is 58 segments before final chapter marker",
                           "segment_index": segment_index,
                           "source_start_codepoint": source_start,
                           "source_end_codepoint_exclusive": source_start + len(raw),
                           "source_start_byte": source_byte_start,
                           "source_end_byte_exclusive": byte_cursor,
                           "next_page_delimiter_codepoint": source_start + len(raw)},
            "image_path": image_path, "image_sha256": digest(images[page_number]),
            "image_full_number": page_number + 17, "regions": {},
            "applicability": applicability, "limitations": limitations,
            "ambiguity_token_count": sum(bool(t["ambiguity"]) for t in tokens),
        })
        entries.append({"path": image_path,
                        "url": f"https://github.com/cicada-solvers/iddqd/blob/{UPSTREAM}/{upstream_path}",
                        "upstream_version": UPSTREAM, "upstream_git_blob": blobs[upstream_path],
                        "acquired_at_utc": acquired,
                        "acquisition": "byte-for-byte copy from existing local checkout; this timestamp is snapshot time, original retrieval known only as 2026-09-13",
                        "source_local_path": f"github/iddqd/{upstream_path}",
                        "sha256": digest(images[page_number]), "bytes": len(images[page_number]),
                        "http_metadata": {}})
    if [p["page_number"] for p in pages] != list(range(56)) or sum(p["rune_count"] for p in pages) != 12956:
        raise ValueError("Unexpected LP2/0..55 coverage")
    corpus = {"schema": 1, "version": VERSION, "derived_at_utc": acquired,
              "source": expected_source,
              "source_encoding": "utf8 strict; CRLF retained in raw and codepoint/byte positions",
              "derivation_script": "scripts/prepare_attempt1.py",
              "derivation_script_sha256": digest(Path(__file__).read_bytes()),
              "rune_alphabet": RUNES, "arithmetic_domain": "GP rune ordinal indices 0..28, distinct from prime values",
              "checks": {"source_sha256_verified": True, "checkout_git_blobs_verified": True,
                         "master_git_blob_comparison": "explicit CRLF-to-LF conversion only for Git blob check",
                         "lp2_segment_count": 58, "full_to_lp2_image_mapping_checked": 58,
                         "known_tail": known_tail, "all_tokens_lossless": True,
                         "unknown_runes": 0},
              "coverage": {"pages": 56, "rune_pages": 55, "runes": 12956,
                           "excluded_rune_pages": [50], "mixed_grid_pages": [49, 51],
                           "candidate_cryptanalysis_executed": 0},
              "pages": pages}
    # All checks precede writing. Partial writes after an I/O failure are kept as
    # evidence, and a future rerun will refuse to overwrite them.
    for page_number in range(56):
        write_exclusive(ROOT / IMAGE_DIR / f"{page_number}.jpg", images[page_number])
    write_exclusive(ROOT / MANIFEST, json_bytes({"schema": 1, "version": VERSION, "entries": entries}))
    write_exclusive(ROOT / CORPUS, json_bytes(corpus))
    print(json.dumps({"status": "passed", "corpus": CORPUS,
                      "corpus_sha256": digest((ROOT / CORPUS).read_bytes()),
                      "manifest": MANIFEST, "manifest_sha256": digest((ROOT / MANIFEST).read_bytes()),
                      "coverage": corpus["coverage"], "source_raw_crlf_preserved": True,
                      "all_execution_finished": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
