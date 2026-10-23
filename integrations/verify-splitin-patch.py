#!/usr/bin/env python3
"""Read-only verification of the optional adapter against a separate checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def verify(checkout: Path) -> dict:
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "splitin-base.json").read_text())
    patch = here / "splitin.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patchSha256"]:
        raise ValueError("Patch differs from the reviewed artifact; reconcile and regenerate its manifest")
    for name, expected in manifest["files"].items():
        path = checkout / name
        if not path.is_file():
            raise ValueError(f"Missing base file: {name}")
        content = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if blob != expected["gitBlob"]:
            raise ValueError(f"Base file changed: {name}; reconcile before applying")
    result = subprocess.run(["git", "-C", str(checkout), "apply", "--check", str(patch)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Patch application check failed")
    return {"ok": True, "baseCommit": manifest["baseCommit"], "patchSha256": manifest["patchSha256"], "checkedBaseFiles": len(manifest["files"]), "applied": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="Clean, separate SplitIn checkout; never modified")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.checkout.resolve()), indent=2))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
