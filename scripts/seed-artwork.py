#!/usr/bin/env python3
"""Upload original starter illustrations through the same restricted image pipeline."""
import argparse
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.map_studio.assets import Upload, decode_image, storage, PRIVATE_BUCKET
from server.map_studio.config import OWNER_ID
from server.map_studio.store import rpc

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    catalog = json.loads((ROOT/'fixtures/artwork/catalog.json').read_text())
    projects = json.loads((ROOT/'fixtures/pilot.json').read_text())['projects']
    actor = {'id': OWNER_ID}
    for project in projects:
        key = project['mapKey']
        for entry in catalog:
            data = (ROOT/'fixtures/artwork'/entry['file']).read_bytes()
            asset_id = str(uuid5(NAMESPACE_URL, f"map-studio:{key}:{hashlib.sha256(data).hexdigest()}"))
            if args.apply:
                await rpc(actor, 'map_studio_get_project', {'p_map_key': key})
                existing = await rpc(actor, 'map_studio_asset_get', {'p_map_key': key, 'p_asset_id': asset_id})
                if existing and existing.get('id'):
                    print(json.dumps({'operation': 'exists', 'mapKey': key, 'name': entry['name']}))
                    continue
                body = Upload(**{k: entry[k] for k in ('name','altText','rights')}, mimeType='image/svg+xml', dataBase64=base64.b64encode(data).decode())
                original, processed, width, height = await decode_image(body)
                digest = hashlib.sha256(processed).hexdigest()
                prefix = f'{key}/{asset_id}'
                for path, content, mime in [(f'{prefix}/original', original, 'image/svg+xml'),(f'{prefix}/{digest}.webp', processed, 'image/webp')]:
                    response = await storage('POST', PRIVATE_BUCKET, path, content, mime)
                    if not response.is_success:
                        verified = await storage('GET', PRIVATE_BUCKET, path)
                        if not verified.is_success or hashlib.sha256(verified.content).digest()!=hashlib.sha256(content).digest():
                            raise SystemExit('Artwork upload failed; original publication unchanged')
                await rpc(actor, 'map_studio_asset_register', {'p_map_key': key, 'p_asset': {
                    'id': asset_id, 'name': entry['name'], 'alt_text': entry['altText'], 'rights': entry['rights'],
                    'mime_type': 'image/svg+xml', 'sha256': digest, 'original_path': f'{prefix}/original',
                    'processed_path': f'{prefix}/{digest}.webp', 'width': width, 'height': height, 'byte_size': len(original), 'state': 'ready'}})
            print(json.dumps({'operation': 'registered' if args.apply else 'dry-run', 'mapKey': key, 'name': entry['name']}))

if __name__ == '__main__':
    asyncio.run(main())
