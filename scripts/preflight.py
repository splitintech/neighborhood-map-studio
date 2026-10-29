#!/usr/bin/env python3
"""Offline release/config inventory. Never contacts providers or applies SQL."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATIONS = ('001_map_studio.sql', '002_owner_sessions.sql', '003_public_delivery.sql')


def inspect(root: Path = ROOT, require_config: bool = False) -> tuple[dict, int]:
    files = []
    for name in MIGRATIONS:
        path = root / 'migrations' / name
        files.append({'name': name, 'present': path.is_file(),
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
    built = (root / 'frontend/dist/index.html').is_file()
    result = {'operation': 'offline-preflight', 'networkRequests': 0, 'databaseWrites': 0,
              'frontendBuilt': built, 'migrations': files, 'configurationChecked': require_config,
              'remoteReadinessVerified': False}
    ok = built and all(item['present'] for item in files)
    if require_config:
        try:
            from server.map_studio.config import Settings
            config = Settings(_env_file=root / '.env')
            missing = config.missing()
            result['configurationReady'] = not missing
            result['missingSettings'] = missing
            result['publicApiManifestsEnabled'] = config.public_manifests_enabled
            ok = ok and not missing
        except Exception:
            # Validation errors may contain supplied input. Never print values.
            result['configurationReady'] = False
            result['configurationError'] = 'invalid_configuration'
            ok = False
    result['localReady'] = ok
    return result, 0 if ok else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-config', action='store_true', help='Validate local secure environment, without printing values')
    args = parser.parse_args()
    result, code = inspect(require_config=args.require_config)
    print(json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
