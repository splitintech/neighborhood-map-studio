#!/usr/bin/env python3
"""Create a Daytona snapshot from a pinned release image.

The image is built by CI and must be referenced by digest.  This script only
registers that image with Daytona; it does not upload source files or embed
credentials in the snapshot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlsplit


class SnapshotError(RuntimeError):
    pass


SNAPSHOT_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
DEFAULT_SNAPSHOT_TIMEOUT = 600
SNAPSHOT_ENTRYPOINT = "/opt/map-studio/start.sh"


def _name(value: str) -> str:
    if not SNAPSHOT_NAME.fullmatch(value):
        raise SnapshotError("snapshot name must contain only lowercase letters, numbers, and hyphens")
    return value


def _image(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise SnapshotError("--image must be a registry image pinned by @sha256 digest")
    try:
        repository, digest = value.rsplit("@sha256:", 1)
    except ValueError as exc:
        raise SnapshotError("--image must be a registry image pinned by @sha256 digest") from exc
    if not repository or any(character in repository for character in "@?#") or "://" in repository:
        raise SnapshotError("--image must be a valid registry image reference")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise SnapshotError("image digest must contain exactly 64 hexadecimal characters")
    return value


def _entrypoint(value: str) -> str:
    if value != SNAPSHOT_ENTRYPOINT:
        raise SnapshotError(f"entrypoint is fixed to {SNAPSHOT_ENTRYPOINT}")
    return value


def _api_url() -> str | None:
    value = os.getenv("DAYTONA_API_URL")
    if value is None:
        return None
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "https" and bool(url.hostname)
            and url.username is None and url.password is None
            and "?" not in value and "#" not in value
            and not any(character.isspace() or ord(character) < 32 for character in value)
            and "\\" not in value
        )
        # Accessing .port also rejects malformed or out-of-range port numbers.
        valid = valid and (url.port is None or url.port > 0)
    except ValueError:
        valid = False
    if not valid:
        raise SnapshotError("DAYTONA_API_URL must be a credential-free HTTPS URL without query or fragment")
    return value


def _apply(name: str, image: str, entrypoint: list[str], timeout: int = DEFAULT_SNAPSHOT_TIMEOUT) -> dict[str, Any]:
    api_url = _api_url()
    try:
        from daytona import CreateSnapshotParams, Daytona, DaytonaConfig, Resources
    except ImportError as exc:  # pragma: no cover
        raise SnapshotError("install requirements-daytona.txt in the isolated SDK environment") from exc
    api_key = os.getenv("DAYTONA_API_KEY")
    if not api_key:
        raise SnapshotError("DAYTONA_API_KEY is required with --apply")
    config = DaytonaConfig(api_key=api_key, api_url=api_url) if api_url else DaytonaConfig(api_key=api_key)
    client = Daytona(config)
    snapshot = client.snapshot.create(CreateSnapshotParams(
        name=name,
        image=image,
        entrypoint=entrypoint,
        resources=Resources(cpu=1, memory=1),
    ), timeout=timeout)
    snapshot_id = getattr(snapshot, "id", None) or getattr(snapshot, "name", None) or name
    return {"operation": "created", "snapshot": str(snapshot_id), "image": image}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create the snapshot; dry-run is the default")
    parser.add_argument("--name", default=os.getenv("DAYTONA_MAP_STUDIO_SNAPSHOT", ""))
    parser.add_argument("--image", default=os.getenv("DAYTONA_MAP_STUDIO_IMAGE", ""))
    parser.add_argument("--entrypoint", default="/opt/map-studio/start.sh")
    parser.add_argument("--timeout", type=int, default=DEFAULT_SNAPSHOT_TIMEOUT, help="snapshot creation timeout in seconds")
    args = parser.parse_args(argv)
    try:
        _api_url()
        if args.timeout <= 0:
            raise SnapshotError("--timeout must be greater than zero")
        if not args.name:
            raise SnapshotError("--name or DAYTONA_MAP_STUDIO_SNAPSHOT is required")
        name = _name(args.name)
        image = _image(args.image)
        entrypoint = _entrypoint(args.entrypoint)
        result = _apply(name, image, [entrypoint], args.timeout) if args.apply else {
            "operation": "dry-run", "timeoutSeconds": args.timeout, "snapshot": name, "image": image, "entrypoint": [entrypoint], "resources": {"cpu": 1, "memoryGiB": 1}
        }
    except SnapshotError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"error": "Snapshot operation failed; check registry access and provider status."}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
