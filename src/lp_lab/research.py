"""Validate evidence links; retrieve prior reasoning without promoting speculation."""
import json

def read_knowledge(root):
    return json.loads((root / "research/knowledge.json").read_text(encoding="utf8"))

def validate(root, knowledge=None):
    doc = read_knowledge(root) if knowledge is None else knowledge
    claims = {c["id"]:c for c in doc["claims"]}
    experiments = {e["id"]:e for e in doc["experiments"]}
    if len(claims)!=len(doc["claims"]) or len(experiments)!=len(doc["experiments"]):
        raise ValueError("Duplicate research ID")
    for e in experiments.values():
        if e["outcome"] not in {"passed","negative","error","timeout","inconclusive"} or not e["coverage"]:
            raise ValueError("Missing scoped experiment outcome")
        artifact = json.loads((root / e["artifact"]).read_text(encoding="utf8"))
        for pointer, expected in e["assertions"].items():
            actual = artifact
            for part in pointer.split("."):
                actual = actual[part]
            if actual != expected:
                raise ValueError(f"Evidence assertion failed: {e['id']} {pointer}")
    for c in claims.values():
        if c["status"] not in {"reproduced","source_reported","conjecture","corrected"}:
            raise ValueError("Unknown claim status")
        if any(e not in experiments for e in c["experiments"]):
            raise ValueError("Unknown experiment")
        if c["status"] == "reproduced" and not any(experiments[e]["outcome"]=="passed" for e in c["experiments"]):
            raise ValueError("Cannot promote a claim without a successful scoped experiment")
        for evidence in c["evidence"]:
            content = (root / evidence["path"]).read_text(encoding="utf8")
            if evidence["anchor"] not in content:
                raise ValueError(f"Unresolved evidence locator: {c['id']}")
    for edge in doc["edges"]:
        if edge["from"] not in claims or edge["to"] not in claims:
            raise ValueError("Dangling graph edge")
        if edge["relation"] == "text_to_known_mechanism" and claims[edge["to"]]["status"] != "reproduced":
            raise ValueError("Conjecture cannot be a verified mechanism")
    for path in (root / "research/feeds").glob("*.json"):
        feed = json.loads(path.read_text(encoding="utf8"))
        if not (root / feed["source"]).is_file() or any(c not in claims for c in feed["claim_ids"]):
            raise ValueError("Broken feed provenance")
    return dict(claims=len(claims),edges=len(doc["edges"]),experiments=len(experiments),status="passed")

def find(root, query):
    doc = read_knowledge(root)
    needle = query.casefold()
    claims = [c for c in doc["claims"] if needle in json.dumps(c,ensure_ascii=False).casefold()]
    experiment_ids = {e for c in claims for e in c["experiments"]}
    experiments = [e for e in doc["experiments"] if e["id"] in experiment_ids or needle in json.dumps(e,ensure_ascii=False).casefold()]
    return dict(query=query,claims=claims,experiments=experiments)
