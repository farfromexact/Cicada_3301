"""Preserve legacy context before updating the project entry point."""
from pathlib import Path
import datetime as dt
import hashlib
import json
ROOT = Path(__file__).resolve().parents[1]

def main():
    manifest = ROOT / "sources/context-manifest.json"
    if manifest.exists():
        raise SystemExit("Context snapshot already exists")
    pin = "0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07"
    paths = [(ROOT / "github/iddqd/liber-primus__keys/liber-primus__keys.txt", "sources/context/known-keys.txt", f"https://github.com/cicada-solvers/iddqd/blob/{pin}/liber-primus__keys/liber-primus__keys.txt", pin),
             (ROOT / "github/iddqd/liber-primus__translation/liber-primus__translation.txt", "sources/context/translation.txt", f"https://github.com/cicada-solvers/iddqd/blob/{pin}/liber-primus__translation/liber-primus__translation.txt", pin),
             (ROOT / "README.md", "sources/context/legacy-README.md", "workspace:README.md", None),
             (ROOT / "SOURCE_MANIFEST.md", "sources/context/legacy-SOURCE_MANIFEST.md", "workspace:SOURCE_MANIFEST.md", None),
             (Path("C:/Users/macon/AppData/Local/Temp/codex-clipboard-53179ba6-35de-497d-b195-d61baea3b1d8.png"), "sources/context/user-layout-reference.png", "user-attachment:codex-clipboard-53179ba6-35de-497d-b195-d61baea3b1d8.png", None)]
    entries = []
    for source, dest, url, version in paths:
        content = source.read_bytes()
        target = ROOT / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries.append(dict(path=dest, url=url, upstream_version=version,
                            acquired_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                            acquisition="local snapshot; original exact retrieval time unknown",
                            sha256=hashlib.sha256(content).hexdigest(), bytes=len(content)))
    manifest.write_text(json.dumps(dict(schema=1, entries=entries), ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print("Saved 5 context sources as data, not executable instructions")

if __name__ == "__main__":
    main()
