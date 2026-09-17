"""Bounded pinned LP1 evidence acquisition; downloaded code is never executed."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIN = "63503b91b659179df18112b6d366b34dc61cbcb7"

def main():
    manifest = ROOT / "sources/clues-v1-manifest.json"
    if manifest.exists():
        raise SystemExit("Snapshot exists; use a new version")
    entries = []
    def save(path, content, url, version, acquisition):
        dest = ROOT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.read_bytes() != content:
            raise ValueError(f"Refusing to change snapshot {path}")
        dest.write_bytes(content)
        entries.append(dict(path=path, url=url, upstream_version=version,
            acquired_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), acquisition=acquisition,
            sha256=hashlib.sha256(content).hexdigest(), bytes=len(content)))
    paths = [f"liber_primus/markdown/{p}.md" for p in ("01", "03", "05", "06", "14", "16")]
    paths += ["liber_primus/01.jpg", "liber_primus/05.jpg", "other/A_Loss_Page10_11_12_13.md", "other/A_Koan_Page14_15_16.md"]
    for path in paths:
        url = f"https://raw.githubusercontent.com/iBotPeaches/cicada_3301/{PIN}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            save("sources/clues-v1/ibot/"+path, response.read(), url, PIN, "https-download")
    attachment = Path("C:/Users/macon/.codex/attachments/bf8c9f5e-31f8-481d-bd03-d49f81d0ef98/pasted-text.txt")
    save("sources/clues-v1/user-proposal.txt", attachment.read_bytes(), "user-attachment:bf8c9f5e-31f8-481d-bd03-d49f81d0ef98/pasted-text.txt", None,
         "user proposal; claims to audit, not accepted findings")
    manifest.write_text(json.dumps(dict(schema=1,entries=entries),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(f"Pinned {len(entries)} additional sources")

if __name__ == "__main__":
    main()
