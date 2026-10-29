#!/usr/bin/env python3
"""Check retained migration provenance; --snapshot verifies original migrated bytes."""
import hashlib,json,pathlib,subprocess,sys
root=pathlib.Path(__file__).resolve().parents[1]
source=json.loads((root/'docs/migration/source-files.json').read_text())
snapshot=json.loads((root/'docs/migration/snapshot.json').read_text())
assert source['source_commit']==snapshot['source_commit']
assert {f['target'] for f in source['files']}=={f['path'] for f in snapshot['files']}
errors=[]
for f in snapshot['files']:
 p=root/f['path']
 if not p.is_file():errors.append('missing '+f['path']);continue
 if '--snapshot' in sys.argv or f['path']=='LICENSE' or p.suffix in {'.png','.webp'}:
  if hashlib.sha256(p.read_bytes()).hexdigest()!=f['sha256']:errors.append('hash mismatch '+f['path'])
 if f['mode']=='100755' and not p.stat().st_mode & 0o111:errors.append('lost executable bit '+f['path'])
 if f['sha256']!=f['source_sha256'] and not f['change']:errors.append('unexplained change '+f['path'])
for p in [root/'README.md',root/'CONTRIBUTING.md',root/'LICENSE',root/'docs/migration/commit-map.txt']:
 if not p.is_file():errors.append('missing '+str(p.relative_to(root)))
if errors:raise SystemExit('\n'.join(errors))
print('Migration inventory verified: '+str(len(snapshot['files']))+' upstream files'+(' (exact snapshot)' if '--snapshot' in sys.argv else ''))
