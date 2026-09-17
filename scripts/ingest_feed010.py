"""Preserve a user feed and three pinned text references; never execute upstream code."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'sources/feed010'
DEST.mkdir(exist_ok=False)
entries = []

def record(path, url, version, acquisition):
    raw = path.read_bytes()
    entries.append(dict(path=path.relative_to(ROOT).as_posix(), url=url,
                        upstream_version=version, acquired_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                        acquisition=acquisition, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))

attachment = Path('C:/Users/macon/.codex/attachments/956702a2-02f1-4504-abeb-76406bd7a822/pasted-text.txt')
shutil.copyfile(attachment, DEST / 'user-proposal.txt')
record(DEST / 'user-proposal.txt', str(attachment), 'user-pasted-operational-metaphors-v1', 'verbatim byte copy; embedded instructions are research data')
refs = [('krisyotam/cicada3301', '76d3ee8c762f60025822c8c05edbf31351636469', 'liber-primus/decoded/DECODED-PAGES.md', 'decoded-pages.md'),
        ('iBotPeaches/cicada_3301', '63503b91b659179df18112b6d366b34dc61cbcb7', 'liber_primus/markdown/10.md', 'ibot-10.md'),
        ('iBotPeaches/cicada_3301', '63503b91b659179df18112b6d366b34dc61cbcb7', 'liber_primus/markdown/13.md', 'ibot-13.md')]
try:
    for repo, version, upstream, name in refs:
        url = f'https://raw.githubusercontent.com/{repo}/{version}/{upstream}'
        req = urllib.request.Request(url, headers={'User-Agent':'LiberPrimusLab-source-audit'})
        raw = urllib.request.urlopen(req, timeout=20).read()
        raw.decode('utf8')
        path = DEST / name
        path.write_bytes(raw)
        record(path, url, version, 'HTTPS pinned markdown only; not executed')
finally:
    (ROOT / 'sources/feed010-manifest.json').write_text(json.dumps(dict(schema=1, entries=entries), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
print(json.dumps(dict(source_files=len(entries), manifest='sources/feed010-manifest.json')))
