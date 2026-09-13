"""Archive FEED-002 and its three GitHub references; execute no upstream code."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def main():
    manifest = ROOT / "sources/feed002-manifest.json"
    if manifest.exists():
        raise SystemExit("Snapshot exists; create a new version")
    api = "https://api.github.com/repos/Wulfic/Cicada3301-Liber_Primus/commits/main"
    with urllib.request.urlopen(api,timeout=30) as response:
        pin = json.load(response)["sha"]
    entries = []
    def save(path,content,url,version,acquisition):
        dest = ROOT / path
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and dest.read_bytes()!=content:
            raise ValueError("Refusing to overwrite source")
        dest.write_bytes(content)
        entries.append(dict(path=path,url=url,upstream_version=version,acquired_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                            acquisition=acquisition,sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)))
    for path in ("MASTER_TRACKER.md","data/key_search_corpus.txt","pages/page_63/README.md"):
        url=f"https://raw.githubusercontent.com/Wulfic/Cicada3301-Liber_Primus/{pin}/{path}"
        with urllib.request.urlopen(url,timeout=30) as response:
            save("sources/feed002/wulfic/"+path,response.read(),url,pin,"https-download; source claims not adopted as verified")
    source=Path("C:/Users/macon/.codex/attachments/1ff5e190-eb6d-4d4e-b5e7-2167fbaee45e/pasted-text.txt")
    save("sources/feed002/user-proposal.txt",source.read_bytes(),"user-attachment:1ff5e190-eb6d-4d4e-b5e7-2167fbaee45e/pasted-text.txt",None,"user feed snapshot")
    manifest.write_text(json.dumps(dict(schema=1,entries=entries),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(files=len(entries),upstream_commit=pin)))

if __name__=="__main__":
    main()
