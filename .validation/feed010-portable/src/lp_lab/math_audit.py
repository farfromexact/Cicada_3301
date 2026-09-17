"""Bounded mathematical checks. No candidate search, prose inference or new data edits."""
import json
import math
from .runes import RUNES, GP, indices
from .clues import matrix_check
from .cipher import transform
from .reference import reference_indices

def phi(n):
    if type(n) is not int or n < 1:
        raise ValueError("phi requires a positive integer")
    return sum(math.gcd(k,n)==1 for k in range(1,n+1))

def symmetry_checks(matrix):
    n=len(matrix)
    if not n or any(len(row)!=n for row in matrix):
        raise ValueError("A nonempty square matrix is required")
    operations={
        "identity":lambda r,c:(r,c), "rotate90":lambda r,c:(n-1-c,r),
        "rotate180":lambda r,c:(n-1-r,n-1-c), "rotate270":lambda r,c:(c,n-1-r),
        "mirror_horizontal":lambda r,c:(n-1-r,c), "mirror_vertical":lambda r,c:(r,n-1-c),
        "transpose":lambda r,c:(c,r), "anti_transpose":lambda r,c:(n-1-c,n-1-r)}
    result={}
    for name,operation in operations.items():
        mismatches=[]
        for r in range(n):
            for c in range(n):
                rr,cc=operation(r,c)
                if matrix[r][c]!=matrix[rr][cc]:
                    mismatches.append(dict(at=[r,c],partner=[rr,cc],value=matrix[r][c],partner_value=matrix[rr][cc]))
        result[name]=dict(equal=not mismatches,compared_positions=n*n,mismatches=mismatches)
    return result

def audit(root):
    inverses=[dict(index=x,inverses=[y for y in range(29) if x*y%29==1]) for x in range(29)]
    field_ok=not inverses[0]["inverses"] and all(len(r["inverses"])==1 for r in inverses[1:])
    residue_groups={}
    for i,p in enumerate(GP):
        residue_groups.setdefault(p%29,[]).append(dict(index=i,rune=RUNES[i],prime_value=p))
    matrix=matrix_check(root)["values"]
    symmetries=symmetry_checks(matrix)
    views={name:symmetry_checks(view)["rotate180"]["equal"] for name,view in (
        ("integer_cell_sum",matrix),
        ("cell_sum_mod29",[[v%29 for v in row] for row in matrix]),
        ("phi_of_cell_sum",[[phi(v) for v in row] for row in matrix]))}
    record=json.loads((root/"data/pages/lp2_56.json").read_text(encoding="utf8"))
    decoded=transform(record["tokens"],**record["parameters"])
    expected=reference_indices(root/record["cross_source"]["path"])
    totients=[dict(stream_index=s["stream_index"],prime=s["prime"],phi_counted=phi(s["prime"]),prime_minus_one=s["prime"]-1)
              for s in decoded["steps"] if s["prime"] is not None]
    wrong_raw=[]
    steps=[]
    for token in record["tokens"]:
        if token["kind"]!="rune":
            wrong_raw.append(token["raw"])
            continue
        i=token["rune"]["index"]
        ordinal=token["rune_ordinal"]
        skipped=ordinal in record["parameters"]["skip"]
        delta=0 if skipped else phi(GP[i])
        output=(i-delta)%29
        wrong_raw.append(RUNES[output])
        steps.append(dict(rune_ordinal=ordinal,input_index=i,gp_prime_value=GP[i],skipped=skipped,
                          delta=delta,output_index=output,expected_index=expected[ordinal],equal=output==expected[ordinal]))
    mismatches=[s["rune_ordinal"] for s in steps if not s["equal"]]
    normal_ok=indices(decoded["raw"])==expected and all(t["phi_counted"]==t["prime_minus_one"] for t in totients)
    return dict(
        status="passed" if field_ok and symmetries["rotate180"]["equal"] and normal_ok and mismatches else "negative",
        field=dict(status="passed" if field_ok else "negative",modulus=29,inverses=inverses,scope="finite arithmetic, not evidence of a cipher"),
        gp_mapping=dict(index_convention="GP[i] = p_(i+1), i=0..28, mathematical primes start p_1=2",
                        full_prime_unique_count=len(set(GP)),mod29_unique_count=len(residue_groups),
                        mod29_collisions={str(k):v for k,v in residue_groups.items() if len(v)>1}),
        matrix=dict(values=matrix,symmetries=symmetries,centrosymmetric_views=views,
                    dependence="A deterministic cellwise map preserves equality of opposite cells; these are not three independent findings."),
        lp2_position_stream=dict(status="passed" if normal_ok else "negative",rune_count=len(expected),
                                 stream_primes_checked=len(totients),totients=totients),
        rune_value_alternative=dict(status="negative" if mismatches else "passed",formula="P=(C-phi(GP[C])) mod29; ordinal 56 passthrough",
                                    mismatches=mismatches,steps=steps,raw="".join(wrong_raw),
                                    scope="Only this alternative on LP2/56 with the registered skip; not an exclusion of all phi constructions"),
        coverage=dict(field_pairs=29*29,matrix_symmetries=8,positions_per_symmetry=25,lp2_runes=85,unsolved_page_candidates=0))
