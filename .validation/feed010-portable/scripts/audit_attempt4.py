"""Independent H008 measurement/arithmetic audit of retained run artifacts.

Does not import the scan engine, its parser, or any known plaintext/reference.
Null randomizations are not rerun: probabilities are recomputed from every saved
control statistic.  This is not independent cryptanalytic confirmation.
"""
from collections import Counter, defaultdict
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
import traceback
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ALPHABET = "ᚠᚢᚦᚩᚱᚳᚷᚹᚻᚾᛁᛄᛇᛈᛉᛋᛏᛒᛖᛗᛚᛝᛟᛞᚪᚫᚣᛡᛠ"
SOFT = "-.,/"
SPEC = "hypotheses/H008-structure-v1.json"
CORPUS = "data/attempt1-corpus-v1.json"


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


class Audit:
    def __init__(self):
        self.checks = 0
        self.failures = []
        self.hashes = {}

    def check(self, condition, label):
        self.checks += 1
        if not condition:
            self.failures.append(label)

    def equal(self, actual, expected, label, floating=False):
        a, b = np.asarray(actual), np.asarray(expected)
        same = a.shape == b.shape
        if same:
            same = (bool(np.allclose(a, b, rtol=1e-10, atol=1e-10, equal_nan=False))
                    if floating else bool(np.array_equal(a, b)))
        self.check(same, label)

    def file(self, name):
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Audit input path escapes workspace")
        if name not in self.hashes:
            self.hashes[name] = digest(path.read_bytes())
        return self.hashes[name]


def reconstruct(original, audit, source_cache):
    """Derive boundaries from raw gaps between independently found rune glyphs."""
    raw, tokens, name = original["raw"], original["tokens"], original["page"]
    audit.check("".join(t["raw"] for t in tokens) == raw, name + " raw reconstruction")
    audit.check(len(tokens) == len(raw), name + " single-codepoint tokens")
    audit.check(digest(raw.encode("utf8")) == original["raw_sha256"], name + " raw digest")
    source = original["source"]
    audit.check(audit.file(source) == original["source_sha256"], name + " source digest")
    audit.check(audit.file(original["image_path"]) == original["image_sha256"], name + " image digest")
    if source not in source_cache:
        source_cache[source] = (ROOT/source).read_bytes()
    master_bytes = source_cache[source]
    master = master_bytes.decode("utf8")
    extraction = original["extraction"]
    first = extraction["source_start_codepoint"]
    last = extraction["source_end_codepoint_exclusive"]
    byte_first = extraction["source_start_byte"]
    byte_last = extraction["source_end_byte_exclusive"]
    audit.check(master[first:last] == raw, name + " original source codepoint span")
    audit.check(master_bytes[byte_first:byte_last] == raw.encode("utf8"), name + " original source byte span")
    positions = [i for i, glyph in enumerate(raw) if glyph in ALPHABET]
    values = [ALPHABET.index(raw[i]) for i in positions]
    selected = []
    groups, mask, eligibility, spans = [], [], [], []
    group, previous = -1, None
    for ordinal, offset in enumerate(positions):
        gap = raw[previous+1:offset] if previous is not None else ""
        broken = previous is None or any(char not in SOFT and not char.isspace() for char in gap)
        if broken:
            group += 1
            spans.append([ordinal, ordinal])
        groups.append(group)
        mask.append(int(not broken and "-" in gap))
        eligibility.append(not broken)
        spans[-1][1] += 1
        token = tokens[offset]
        audit.check(token["kind"] == "rune" and token["rune"]["index"] == values[ordinal]
                    and token["rune_ordinal"] == ordinal, name + f" rune mapping {ordinal}")
        selected.append(token)
        previous = offset
    byte_at = byte_first
    for offset, token in enumerate(tokens):
        audit.check(token["raw"] == raw[offset] and token["source_offset"] == offset
                    and token["id"] == f"{name}:{offset}" and token["page"] == name
                    and token["source_global_offset"] == first+offset
                    and token["source_global_byte_offset"] == byte_at,
                    name + f" preserved token coordinates {offset}")
        byte_at += len(raw[offset].encode("utf8"))
    audit.equal(values, original["indices"], name + " original values")
    audit.check(len(values) == original["rune_count"], name + " rune count")
    return dict(page=name, page_number=original["page_number"], indices=values,
                groups=groups, hyphen_mask=mask, boundary_eligible=eligibility,
                segments=spans, rune_tokens=selected)


def measurements(pages):
    lag_counts, g_values, tables = [], [], []
    occurrences = defaultdict(list)
    for page in pages:
        values = page["indices"]
        for lag in range(1, 30):
            lag_counts.append(sum(values[i] == values[i+lag]
                                  for start, end in page["segments"]
                                  for i in range(start, end-lag)))
        table = [[0, 0] for _ in range(29)]
        for i, value in enumerate(values):
            if page["boundary_eligible"][i]:
                table[value][page["hyphen_mask"][i]] += 1
        total = sum(map(sum, table))
        cols = [sum(row[j] for row in table) for j in (0, 1)]
        terms = []
        if total and min(cols):
            for row in table:
                for j, observed in enumerate(row):
                    if observed:
                        terms.append(observed * math.log(observed * total / (sum(row)*cols[j])))
        g_values.append(max(0.0, 2*math.fsum(terms)))
        tables.append(table)
        for start, end in page["segments"]:
            for i in range(start, end-3):
                occurrences[tuple(values[i:i+4])].append((page["page"], i))
    contributions = []
    for key, locs in occurrences.items():
        counts = list(Counter(name for name, _ in locs).values())
        pairs = sum(counts[i]*counts[j] for i in range(len(counts)) for j in range(i+1, len(counts)))
        if pairs:
            contributions.append((pairs, key, locs))
    contributions.sort(key=lambda row: (-row[0], row[1]))
    return lag_counts, g_values, sum(row[0] for row in contributions), tables, contributions


def standardize(observed, null):
    """Use scalar fsum arithmetic, not the engine's numpy mean/std path."""
    observed = [float(x) for x in observed]
    rows = np.vstack((np.asarray(observed), null))
    means, deviations, active = [], [], []
    z = np.zeros(rows.shape, dtype=float)
    for column in range(len(observed)):
        vals = rows[:, column].tolist()
        mean = math.fsum(vals)/len(vals)
        sd = math.sqrt(math.fsum((x-mean)**2 for x in vals)/len(vals))
        discrimination = max(vals) != min(vals) and sd > 0
        means.append(mean)
        deviations.append(sd if discrimination else 0.0)
        active.append(discrimination)
        if discrimination:
            z[:, column] = [(x-mean)/sd for x in vals]
    maxima = [max((z[i, col] for col, flag in enumerate(active) if flag), default=0.0)
              for i in range(1, len(rows))]
    p = [(1+sum(value >= z[0, col]-1e-12 for value in maxima))/len(rows) if flag else 1.0
         for col, flag in enumerate(active)]
    return dict(observed=observed, mean=means, std=deviations, discriminating=active,
                observed_z=z[0], null_z=z[1:], control_max_z=maxima,
                p_adjusted=p, lead=[flag and value <= .01/3 for flag, value in zip(active, p)])


def check_location(loc, pages, audit):
    page = pages[loc["page"]]
    start, length = loc["ordinal"], loc["length"]
    end = start+length
    audit.check(0 <= start < end <= len(page["indices"]), "location ordinal range")
    expected_tokens = page["rune_tokens"][start:end]
    expected_values = page["indices"][start:end]
    audit.check(loc["indices"] == expected_values and loc["glyphs"] == "".join(ALPHABET[i] for i in expected_values),
                "location exact glyphs " + loc["page"])
    audit.check(loc["tokens"] == expected_tokens, "location full original tokens " + loc["page"])
    audit.check(loc["token_ids"] == [t["id"] for t in expected_tokens]
                and loc["source_offsets"] == [t["source_offset"] for t in expected_tokens]
                and loc["image_lines"] == [t["line"] for t in expected_tokens],
                "location source mapping " + loc["page"])
    audit.check(page["groups"][start] == page["groups"][end-1], "location respects hard segment")


def audit_run(run, audit):
    spec, frozen = read_json(ROOT/SPEC), read_json(run/"frozen-spec.json")
    record = read_json(run/"record.json")
    saved = read_json(run/"statistics.json")
    original = read_json(ROOT/CORPUS)
    prepared = read_json(run/"prepared-inputs.json")
    coverage = read_json(run/"coverage.json")
    drill = read_json(run/"drilldown.json")
    audit.check(spec == frozen, "current spec exactly equals frozen spec")
    audit.check(audit.file(SPEC) == record["spec_sha256"], "registered spec digest")
    audit.check(audit.file(CORPUS) == record["corpus_sha256"] == spec["data_versions"][0]["sha256"], "registered corpus digest")
    audit.check(record["complete"] and record["controls_completed"] == 999
                and saved["status"] == "completed" and saved["completed_control_replicates"] == 999,
                "999 complete control corpora")
    audit.check(saved["seed"] == 33010804 and saved["family_alpha"] == .01/3
                and saved["tie_tolerance"] == 1e-12, "registered seed and gates")
    source_cache = {}
    reconstructed = [reconstruct(page, audit, source_cache) for page in original["pages"]]
    audit.check([p["page_number"] for p in reconstructed] == list(range(56)), "full ordered universe 0..55")
    audit.check(len(prepared) == len(coverage) == 56, "all coverage and input rows retained")
    for raw_page, expected, actual, row in zip(original["pages"], reconstructed, prepared, coverage):
        for key, value in expected.items():
            audit.check(actual[key] == value, "independent parser " + expected["page"] + " " + key)
        n = len(expected["indices"])
        audit.check(row["page_or_section"] == expected["page"] and row["rune_count"] == n
                    and row["applicability"] == bool(n), "per-page coverage identity and applicability")
        audit.check(row["segments"] == expected["segments"], "coverage segment boundaries")
        counts = [expected["indices"].count(i) for i in range(29)]
        audit.equal(row["symbol_counts"], counts, "descriptive counts")
        expected_ic = sum(c*(c-1) for c in counts)/(n*(n-1)) if n > 1 else None
        audit.check(row["IC"] == expected_ic, "descriptive IC")
        if not n:
            audit.check(bool(row["inapplicability_reason"]) and row["result_status"] == "inconclusive", "empty page not negative")
        for key in ("raw_sha256", "source_sha256", "image_sha256", "version", "extraction"):
            audit.check(actual["metadata"][key] == raw_page[key], "retained source metadata " + key)
    pages = [page for page in reconstructed if page["indices"]]
    audit.check(len(pages) == 55 and sum(len(p["indices"]) for p in pages) == 12956, "55 applicable pages 12956 runes")
    audit.check([p["page"] for p in reconstructed if not p["indices"]] == ["LP2/50"], "unique empty page")
    a, b, c, tables, motifs = measurements(pages)
    npz_path = run/"null-statistics.npz"
    with np.load(npz_path, allow_pickle=False) as pack:
        arrays = {key: pack[key] for key in pack.files}
    fields = {"observed", "null", "mean", "std", "discriminating", "observed_z", "null_z", "control_max_z", "p_adjusted", "lead"}
    audit.check(set(arrays) == {f+"_"+field for f in "AB" for field in fields} | {"C_null"}, "NPZ fixed member inventory")
    summaries = {}
    for family, measured, width in (("A", a, 1595), ("B", b, 55)):
        null = arrays[family+"_null"]
        audit.check(null.shape == (999, width), family + " null dimensions")
        audit.check(np.isfinite(null).all() and (null >= 0).all(), family + " finite nonnegative controls")
        if family == "A":
            audit.check(null.dtype.kind in "iu", "A integral control counts")
        fresh = standardize(measured, null)
        summaries[family] = fresh
        for field, expected in fresh.items():
            floating = field not in {"discriminating", "lead"} and (family == "B" or field != "observed")
            audit.equal(arrays[family+"_"+field], expected, family+" NPZ "+field, floating=floating)
            if field != "null_z":
                audit.equal(saved["families"][family][field], expected, family+" JSON "+field, floating=floating)
    null_c = arrays["C_null"]
    audit.check(null_c.shape == (999,) and null_c.dtype.kind in "iu" and (null_c >= 0).all(), "C integer control dimensions")
    c_rows = [c] + null_c.tolist()
    mean_c = math.fsum(c_rows)/1000
    sd_c = math.sqrt(math.fsum((v-mean_c)**2 for v in c_rows)/1000)
    pc = (1+sum(v >= c for v in null_c))/1000
    dc = max(c_rows) != min(c_rows)
    expected_c = dict(observed=c, mean=mean_c, std=sd_c, discriminating=dc, p_adjusted=pc, lead=dc and pc <= .01/3)
    summaries["C"] = expected_c
    for field, expected in expected_c.items():
        audit.equal(saved["families"]["C"][field], expected, "C JSON " + field, floating=field in {"mean", "std", "p_adjusted"})
    for j, page in enumerate(pages):
        row = coverage[page["page_number"]]["actual_parameter_coverage"]
        for family, selection in (("A", slice(j*29, (j+1)*29)), ("B", j)):
            for field in ("observed", "p_adjusted", "lead", "discriminating"):
                expected = np.asarray(summaries[family][field])[selection]
                audit.equal(row[family][field], expected, "coverage metric " + page["page"] + family + field,
                            floating=field in {"observed", "p_adjusted"})
        audit.check(row["C"]["valid_windows"] == sum(max(0, e-s-3) for s, e in page["segments"]), "coverage C windows")

    indexed = {p["page"]: p for p in pages}
    ai = max(range(1595), key=lambda i: summaries["A"]["observed_z"][i])
    pi, lo = divmod(ai, 29)
    p, lag = pages[pi], lo+1
    pair_starts = [i for start, end in p["segments"] for i in range(start, end-lag)
                   if p["indices"][i] == p["indices"][i+lag]]
    audit.check((drill["A"]["column"], drill["A"]["page"], drill["A"]["lag"], drill["A"]["count"])
                == (ai, p["page"], lag, len(pair_starts)), "A fixed strongest localization")
    audit.check([(pair["left"]["ordinal"], pair["right"]["ordinal"]) for pair in drill["A"]["pairs"]]
                == [(i, i+lag) for i in pair_starts], "A complete matching pair list")
    for pair in drill["A"]["pairs"]:
        check_location(pair["left"], indexed, audit)
        check_location(pair["right"], indexed, audit)
    bi = max(range(55), key=lambda i: summaries["B"]["observed_z"][i])
    audit.check(drill["B"]["column"] == bi and drill["B"]["page"] == pages[bi]["page"], "B fixed strongest localization")
    audit.equal(drill["B"]["counts_by_rune_nonhyphen_hyphen"], tables[bi], "B full 29x2 table")
    audit.check(drill["B"]["eligible"] == pages[bi]["boundary_eligible"] and drill["B"]["hyphen_mask"] == pages[bi]["hyphen_mask"], "B full masks")
    audit.check([loc["ordinal"] for loc in drill["B"]["rune_locations"]] == list(range(len(pages[bi]["indices"]))), "B all rune locations")
    for loc in drill["B"]["rune_locations"]:
        check_location(loc, indexed, audit)
    audit.check(drill["C"]["count"] == c and drill["C"]["distinct_crosspage_motifs"] == len(motifs), "C localized total")
    motif_table = [dict(indices=list(key), glyphs="".join(ALPHABET[x] for x in key), crosspage_pairs=count,
                        occurrences=[dict(page=name, ordinal=i) for name, i in locs]) for count, key, locs in motifs]
    audit.check(drill["C"]["motif_table"] == motif_table, "C complete exact motif table")
    if motifs:
        count, key, locs = motifs[0]
        selected = drill["C"]["selected_motif"]
        audit.check(selected["indices"] == list(key) and selected["crosspage_pairs"] == count,
                    "C fixed strongest motif lexicographic tie break")
        audit.check([(loc["page"], loc["ordinal"]) for loc in selected["occurrences"]] == locs, "C all motif occurrences")
        for loc in selected["occurrences"]:
            check_location(loc, indexed, audit)
        extensions = []
        for at, (name, i) in enumerate(locs):
            for other, j in locs[at+1:]:
                if name == other:
                    continue
                x, y = indexed[name], indexed[other]
                xs, xe = next((s, e) for s, e in x["segments"] if s <= i < e)
                ys, ye = next((s, e) for s, e in y["segments"] if s <= j < e)
                left = 0
                for offset in range(1, min(i-xs, j-ys)+1):
                    if x["indices"][i-offset] != y["indices"][j-offset]:
                        break
                    left = offset
                right = 4
                for offset in range(4, min(xe-i, ye-j)):
                    if x["indices"][i+offset] != y["indices"][j+offset]:
                        break
                    right = offset+1
                extensions.append((name, i-left, other, j-left, left+right))
        audit.check([(e["left"]["page"], e["left"]["ordinal"], e["right"]["page"], e["right"]["ordinal"], e["left"]["length"])
                     for e in selected["extensions"]] == extensions, "C deterministic complete maximal extensions")
        for extension in selected["extensions"]:
            check_location(extension["left"], indexed, audit)
            check_location(extension["right"], indexed, audit)
            audit.check(extension["left"]["indices"] == extension["right"]["indices"], "C extension exact equality")
    leads = {family: any(summaries[family]["lead"]) for family in "AB"}
    leads["C"] = bool(expected_c["lead"])
    audit.check(record["formal_lead_families"] == leads, "record formal gates")
    audit.check(record["status"] == ("passed" if any(leads.values()) else "negative"), "record final status")
    for path, expected in record["code_version"].items():
        audit.check(audit.file(path) == expected, "scoped frozen code " + path)
    archive = run/"reproduction-bundle.zip"
    audit.check(digest(archive.read_bytes()) == record["input_bundle_sha256"], "input archive digest")
    members = []
    with zipfile.ZipFile(archive) as z:
        audit.check(z.testzip() is None, "all ZIP members CRC")
        names = z.namelist()
        audit.check(len(names) == len(set(names)) == record["input_bundle_members"], "archive unique expected member count")
        for name in names:
            payload = z.read(name)
            audit.check(digest(payload) == audit.file(name) and payload == (ROOT/name).read_bytes(), "ZIP byte-for-byte current file " + name)
            members.append({"path": name, "bytes": len(payload), "sha256": digest(payload)})
    for name in ("record.json", "frozen-spec.json", "prepared-inputs.json", "statistics.json", "drilldown.json", "coverage.json", "null-statistics.npz", "reproduction-bundle.zip"):
        audit.file((run/name).relative_to(ROOT).as_posix())
    return dict(coverage={"pages": 56, "applicable_pages": 55, "runes": 12956,
                          "A_observed_metrics": len(a), "B_observed_metrics": len(b), "C_crosspage_pairs": c,
                          "control_replicates": 999, "recomputed_probabilities": 1651},
                formal_lead_families=leads, minimum_adjusted_p={"A": min(summaries["A"]["p_adjusted"]),
                    "B": min(summaries["B"]["p_adjusted"]), "C": pc},
                archive_members=members,
                invariant_scope="A/B permit separate page-wise bijections; C only a common global bijection. No transformed diagnostic family executed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/attempt4-H008-v1")
    parser.add_argument("--out", default="reviews/attempt-004-audit.json")
    args = parser.parse_args()
    out, run = ROOT/args.out, ROOT/args.run
    if out.exists():
        raise FileExistsError("Audit records are append-only; choose a new output version")
    if not out.resolve().is_relative_to((ROOT/"reviews").resolve()) or not run.resolve().is_relative_to((ROOT/"runs").resolve()):
        raise ValueError("Audit paths must stay in reviews/ and runs/")
    audit = Audit()
    result = dict(schema=1, audited_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  scope="Independent retained-measurement, source-coordinate, probability and archive audit; not independent cryptanalytic confirmation.",
                  limitations=["Does not regenerate null permutations or rotations; recomputes correction from all retained controls.",
                               "Does not independently transcribe images or establish any plaintext/key.",
                               "Same-data drilldown remains post-selection exploratory."],
                  audit_script_sha256=digest(Path(__file__).read_bytes()))
    try:
        result.update(audit_run(run, audit))
    except Exception as exc:
        audit.failures.append(repr(exc))
        result["exception_traceback"] = traceback.format_exc()
    result.update(status="passed" if not audit.failures else "failed", checks=audit.checks,
                  failures=audit.failures, input_hashes=audit.hashes,
                  finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({key: result.get(key) for key in ("status", "checks", "failures", "coverage", "minimum_adjusted_p")}, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
