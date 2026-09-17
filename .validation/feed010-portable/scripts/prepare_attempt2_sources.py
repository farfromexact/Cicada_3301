"""Acquire three frozen H001 source artifacts without executing upstream code."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IBOT = "63503b91b659179df18112b6d366b34dc61cbcb7"
IDDQD = "0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07"
RUN = ROOT / "runs/attempt2-source-preparation-v1"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def exclusive(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf8")


def main():
    targets = [ROOT / "sources/attempt2", ROOT / "sources/attempt2-known-manifest.json", RUN]
    if any(path.exists() for path in targets):
        raise FileExistsError("Refusing to overwrite attempt2 acquisition outputs")
    RUN.mkdir(parents=True)
    started = now()
    entries, operations = [], []
    status, exit_code, error = "passed", 0, ""
    try:
        for page in (3, 4):
            local = f"liber-primus__images--full/{page:02}.jpg"
            command = ["git", "-C", str(ROOT / "github/iddqd"), "ls-tree", IDDQD, "--", local]
            result = subprocess.run(command, capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf8", errors="replace"))
            descriptor, found = result.stdout.decode("utf8").strip().split("\t", 1)
            mode, kind, object_id = descriptor.split()
            if found != local or kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("Unexpected pinned Git tree entry")
            payload = (ROOT / "github/iddqd" / local).read_bytes()
            computed_blob = hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()
            if computed_blob != object_id:
                raise ValueError("Image differs from pinned Git blob")
            path = f"sources/attempt2/iddqd/LP1-{page:02}.jpg"
            exclusive(ROOT / path, payload)
            entries.append(dict(path=path, url=f"https://github.com/cicada-solvers/iddqd/blob/{IDDQD}/{local}",
                                upstream_version=IDDQD, acquired_at_utc=now(), acquisition="verified local Git blob copy",
                                sha256=sha256(payload), bytes=len(payload), git_blob=object_id))
            operations.append(dict(operation="local Git blob validation and copy", command=command,
                                   stdout=result.stdout.decode("utf8"), stderr=result.stderr.decode("utf8"),
                                   exit_code=result.returncode, output=path, sha256=sha256(payload)))
        url = f"https://raw.githubusercontent.com/iBotPeaches/cicada_3301/{IBOT}/liber_primus/markdown/04.md"
        requested = now()
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read()
            http_status, final_url = response.status, response.url
        if http_status != 200 or b"### Method" not in payload or b"### Plaintext" not in payload:
            raise ValueError("Unexpected source04 HTTP payload")
        path = "sources/attempt2/ibot/liber_primus/markdown/04.md"
        exclusive(ROOT / path, payload)
        entries.append(dict(path=path, url=url, upstream_version=IBOT, acquired_at_utc=now(),
                            acquisition="https-download", sha256=sha256(payload), bytes=len(payload)))
        operations.append(dict(operation="fixed URL acquisition", requested_at_utc=requested,
                               url=url, final_url=final_url, http_status=http_status, output=path,
                               sha256=sha256(payload), bytes=len(payload), status="passed"))
    except Exception:
        status, exit_code, error = "error", 1, traceback.format_exc()
    exclusive(ROOT / "sources/attempt2-known-manifest.json", json_bytes(dict(schema=1, entries=entries)))
    stdout = json.dumps(dict(status=status, artifacts=len(entries), operations=operations), ensure_ascii=False) + "\n"
    exclusive(RUN / "stdout.txt", stdout.encode("utf8"))
    exclusive(RUN / "stderr.txt", error.encode("utf8"))
    exclusive(RUN / "record.json", json_bytes(dict(schema=1, status=status, exit_code=exit_code,
              started_at_utc=started, finished_at_utc=now(),
              scope="Two pinned original LP1 images and one pinned source markdown; no candidate decryption",
              script_sha256=sha256(Path(__file__).read_bytes()), operations=operations,
              manifest="sources/attempt2-known-manifest.json")))
    print(stdout, end="")
    if error:
        print(error, end="")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
