"""Append-only audit of a frozen geometric measurement proposal."""
from pathlib import Path
import argparse
import datetime as dt
import json
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from lp_lab.geometry_audit import audit
from lp_lab.provenance import code_snapshot, sha256, verify_sources

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
spec_path = 'hypotheses/FEED010-geometry-audit-v1.json'
spec = json.loads((ROOT/spec_path).read_text(encoding='utf8'))
snapshot = code_snapshot(ROOT)
inputs = [*spec['inputs'], spec_path, 'sources/feed010/user-proposal.txt', 'sources/feed010-manifest.json']
record = dict(started_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), hypothesis=spec,
              code_version=snapshot, data_version={p:sha256(ROOT/p) for p in inputs}, random_seed=None,
              command=[sys.executable, '-X', 'utf8', 'scripts/check_geometry.py', *sys.argv[1:]],
              status='running', next_step=spec['next_step'])
with zipfile.ZipFile(args.out/'audit-bundle.zip','w',compression=zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(set([*snapshot['files'], *inputs])):
        bundle.write(ROOT/path,path)
record['bundle_sha256'] = sha256(args.out/'audit-bundle.zip')
try:
    record['sources_verified'] = verify_sources(ROOT)
    result = audit(ROOT)
    (args.out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if code_snapshot(ROOT) != snapshot:
        raise RuntimeError('Code changed during audit')
    record.update(status=result['status'], actual_coverage=result['coverage'], exit_code=0 if result['status']=='passed' else 1)
    output=json.dumps(dict(status=result['status'],grids={p:dict(unique_sequences=g['unique_sequences'],ring_sums=g['ring_sums'],controls=g['controls']) for p,g in result['grids'].items()}))
    print(output)
    (args.out/'stdout.txt').write_text(output+'\n',encoding='utf8')
    (args.out/'stderr.txt').write_text('',encoding='utf8')
except Exception as exc:
    record.update(status='error',exit_code=1,error=repr(exc))
    (args.out/'stderr.txt').write_text(repr(exc)+'\n',encoding='utf8')
    (args.out/'stdout.txt').write_text('',encoding='utf8')
    print(repr(exc),file=sys.stderr)
record['finished_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
(args.out/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
sys.exit(record['exit_code'])
