from pathlib import Path
import hashlib
import json

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_entries(root):
    entries = []
    manifests = sorted((root / "sources").glob("*manifest.json"))
    if not manifests:
        raise ValueError("No source manifests")
    for path in manifests:
        entries.extend(json.loads(path.read_text(encoding="utf8"))["entries"])
    return entries

def verify_sources(root):
    entries = source_entries(root)
    failures = []
    for entry in entries:
        path = root / entry["path"]
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Source path escapes repository")
        if not path.exists() or sha256(path) != entry["sha256"]:
            failures.append(entry["path"])
    if failures:
        raise ValueError(f"Source integrity failure: {failures}")
    return len(entries)

def code_snapshot(root):
    paths = [root / "pyproject.toml"]
    for directory in ("src", "scripts", "tests"):
        paths += sorted((root / directory).rglob("*.py"))
    entries = {p.relative_to(root).as_posix():sha256(p) for p in sorted(paths)}
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return dict(algorithm="sha256-of-sorted-path-to-sha256-json", digest=digest, files=entries)
