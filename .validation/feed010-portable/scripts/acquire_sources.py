"""Explicit small source acquisition; no upstream code is imported or executed."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PIN = "63503b91b659179df18112b6d366b34dc61cbcb7"
IDDQD = "0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07"

def main():
    target = ROOT / "sources/manifest.json"
    if target.exists():
        raise SystemExit("Snapshot exists: create a new version, do not overwrite")
    entries = []
    def save(path, content, url, version, acquisition, headers=None):
        dest = ROOT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        entries.append(dict(path=path, url=url, upstream_version=version,
                            acquired_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                            acquisition=acquisition, sha256=hashlib.sha256(content).hexdigest(),
                            bytes=len(content), http_metadata=headers or {}))
    upstream = ["liber_primus/markdown/73.md", "liber_primus/markdown/74.md",
                "other/Gematria_Primus.md", "liber_primus/README.md", "LICENSE.md",
                "liber_primus/73.jpg", "liber_primus/74.jpg",
                "tool/app/Actions/Ciphers/GeneratePlaintextFromPrimeShiftedCipher.php"]
    for path in upstream:
        url = f"https://raw.githubusercontent.com/iBotPeaches/cicada_3301/{PIN}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            save("sources/ibot/" + path, response.read(), url, PIN, "https-download",
                 {k: response.headers.get(k) for k in ("ETag", "Last-Modified")})
    url = "https://www.cicadasolvers.com/quickstart/"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            save("sources/quickstart.html", response.read(), url, None, "https-download",
                 {k: response.headers.get(k) for k in ("ETag", "Last-Modified")})
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        save("sources/quickstart.html", (ROOT / "official/cicadasolvers-quickstart.html").read_bytes(),
             url, None, "existing local snapshot; original retrieval day 2026-09-13; new request HTTP 403; live text separately read with web tool")
    for path in ["liber-primus__transcription--master/liber-primus__transcription--master.txt",
                 "liber-primus__images--unsolved/56.jpg", "liber-primus__images--unsolved/57.jpg",
                 "2013/03/gematria-primus.jpg"]:
        content = (ROOT / "github/iddqd" / path).read_bytes()
        save("sources/iddqd/" + path, content,
             f"https://github.com/cicada-solvers/iddqd/blob/{IDDQD}/{path}", IDDQD,
             "copied-from-existing-checkout; original retrieval time only known as 2026-09-13 per legacy manifest")
    target.write_text(json.dumps(dict(schema=1, entries=entries), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Saved {len(entries)} pinned/source-hashed files; upstream scripts not executed")

if __name__ == "__main__":
    main()
