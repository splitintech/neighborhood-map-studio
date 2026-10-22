#!/usr/bin/env python3
"""Register reviewed pilot inventories; dry-run by default, no business mutation UI."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.map_studio.config import OWNER_ID, OWNER_EMAIL
from server.map_studio.storage import supabase_request

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    fixture = json.loads((ROOT / 'fixtures/pilot.json').read_text())
    for item in fixture['projects']:
        project = {k: item[k] for k in ('mapKey', 'title', 'city', 'publicPath', 'center', 'sourceRevision')}
        document = {"schemaVersion": 1, "mapKey": item["mapKey"], "theme": "original",
                    "layers": [{"id": f"business-{index}", "kind": "business",
                                "name": business["name"], "businessId": business["id"],
                                "visible": True, "opacity": 1, "minZoom": 0, "maxZoom": 24,
                                "highlight": "none"}
                               for index, business in enumerate(item["businesses"]) if business.get("location")]}
        if args.apply:
            response = await supabase_request('POST', '/rest/v1/rpc/map_studio_register_project',
                json_body={'p_project': project, 'p_businesses': item['businesses'], 'p_document': document,
                           'p_owner_id': OWNER_ID, 'p_owner_email': OWNER_EMAIL})
            if not response.is_success:
                raise SystemExit(f"Registration failed for {item['mapKey']} (HTTP {response.status_code}); no provider details printed")
        print(json.dumps({'operation': 'registered' if args.apply else 'dry-run',
                          'mapKey': item['mapKey'], 'inventory': item['inventory']}))

if __name__ == '__main__':
    asyncio.run(main())
