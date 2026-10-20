#!/usr/bin/env python3
"""Create or start the single Neighborhood Map Studio Daytona sandbox.

This command is intentionally operator-run.  It never provisions in response
to a browser request, and it prints a dry-run plan unless ``--apply`` is set.
The API key is read by the Daytona SDK and is never included in sandbox
environment variables or JSON output.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


SANDBOX_NAME = "neighborhood-map-studio-runtime"
DEFAULT_PORT = 3000
DEFAULT_AUTOSTOP_MINUTES = 15
DEFAULT_COLD_START_TIMEOUT = 60
DEFAULT_BUDGET_CAP_DOLLARS = 100
DEFAULT_EXPECTED_HOURS = 200
HEALTH_TIMEOUT_SECONDS = 10
APP_REQUIRED_ENV = (
    "MAP_STUDIO_ORIGIN",
    "MAP_STUDIO_GITHUB_CLIENT_ID",
    "MAP_STUDIO_GITHUB_CLIENT_SECRET",
    "MAP_STUDIO_SESSION_SECRET",
    "MAP_STUDIO_SUPABASE_URL",
    "MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY",
)
APP_OPTIONAL_ENV = (
    "MAP_STUDIO_ENVIRONMENT",
    "MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED",
    "MAP_STUDIO_SESSION_HOURS",
)
APP_ENV_ALLOWLIST = APP_REQUIRED_ENV + APP_OPTIONAL_ENV + ("PORT",)
SAFE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class ProvisionError(RuntimeError):
    """A safe, operator-facing configuration or lifecycle error."""


@dataclass(frozen=True)
class Config:
    name: str
    snapshot: str
    public_transport: bool
    port: int
    autostop_minutes: int
    start_timeout: int
    budget_cap_dollars: int
    expected_hours: float
    app_env: dict[str, str]


def _positive_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ProvisionError(f"{label} must be an integer") from exc
    if result <= 0:
        raise ProvisionError(f"{label} must be greater than zero")
    return result


def _nonnegative_float(value: str, label: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ProvisionError(f"{label} must be a number") from exc
    if not math.isfinite(result) or result < 0:
        raise ProvisionError(f"{label} must be finite and non-negative")
    return result


def _app_environment(port: int, *, required: bool) -> dict[str, str]:
    missing = [name for name in APP_REQUIRED_ENV if not os.getenv(name)]
    if required and missing:
        raise ProvisionError("missing required application environment: " + ", ".join(missing))
    values = {name: os.environ[name] for name in APP_ENV_ALLOWLIST if os.getenv(name) is not None}
    if required:
        origin = urlsplit(values["MAP_STUDIO_ORIGIN"])
        supabase = urlsplit(values["MAP_STUDIO_SUPABASE_URL"])
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}:
            raise ProvisionError("MAP_STUDIO_ORIGIN must be a credential-free HTTPS origin")
        if supabase.scheme != "https" or not supabase.hostname or supabase.username or supabase.password or supabase.query or supabase.fragment or supabase.path not in {"", "/"}:
            raise ProvisionError("MAP_STUDIO_SUPABASE_URL must be a credential-free HTTPS origin")
        if len(values["MAP_STUDIO_SESSION_SECRET"]) < 32:
            raise ProvisionError("MAP_STUDIO_SESSION_SECRET must contain at least 32 characters")
    values["PORT"] = str(port)
    return values


def _validate_name(value: str) -> str:
    if value != SANDBOX_NAME or not SAFE_NAME.fullmatch(value):
        raise ProvisionError(f"sandbox name is fixed to {SANDBOX_NAME}")
    return value


def _fixed_port(value: str) -> int:
    port = _positive_int(value, "port")
    if port != DEFAULT_PORT:
        raise ProvisionError(f"port is fixed to {DEFAULT_PORT}")
    return port


def _health_command(port: int) -> str:
    # Port is validated as an integer before interpolation; no request value or
    # user-provided shell fragment reaches the sandbox process.
    return f"python -c 'import urllib.request; r=urllib.request.urlopen(\"http://127.0.0.1:{port}/healthz\", timeout=5); assert r.status == 200'"


def _config(args: argparse.Namespace) -> Config:
    snapshot = args.snapshot or os.getenv("DAYTONA_MAP_STUDIO_SNAPSHOT", "")
    public_transport = bool(args.public_transport)
    if public_transport and os.getenv("MAP_STUDIO_PUBLIC_TRANSPORT_AUTH_CONFIGURED") != "1":
        raise ProvisionError(
            "--public-transport requires MAP_STUDIO_PUBLIC_TRANSPORT_AUTH_CONFIGURED=1 "
            "after application OAuth and owner authorization are configured"
        )
    if args.apply and not snapshot:
        raise ProvisionError("DAYTONA_MAP_STUDIO_SNAPSHOT or --snapshot is required with --apply")
    if args.apply and not os.getenv("DAYTONA_API_KEY"):
        raise ProvisionError("DAYTONA_API_KEY is required with --apply")
    port = _fixed_port(str(args.port))
    required_app_env = args.apply or public_transport
    app_env = _app_environment(port, required=required_app_env)
    return Config(
        name=_validate_name(args.name),
        snapshot=snapshot,
        public_transport=public_transport,
        port=port,
        autostop_minutes=_positive_int(str(args.autostop_minutes), "autostop-minutes"),
        start_timeout=_positive_int(str(args.start_timeout), "start-timeout"),
        budget_cap_dollars=_positive_int(
            os.getenv("DAYTONA_MAP_STUDIO_BUDGET_CAP_DOLLARS", str(DEFAULT_BUDGET_CAP_DOLLARS)),
            "budget cap dollars",
        ),
        expected_hours=_nonnegative_float(
            os.getenv("DAYTONA_MAP_STUDIO_EXPECTED_HOURS", str(DEFAULT_EXPECTED_HOURS)),
            "expected hours",
        ),
        app_env=app_env,
    )


def _plan(config: Config, *, apply: bool) -> dict[str, Any]:
    return {
        "operation": "apply" if apply else "dry-run",
        "sandbox": config.name,
        "snapshotConfigured": bool(config.snapshot),
        "port": config.port,
        "transport": "public-preview" if config.public_transport else "private-preview",
        "autoStopMinutes": config.autostop_minutes,
        "coldStartTimeoutSeconds": config.start_timeout,
        "applicationEnvironment": sorted(config.app_env),
        "wakeMode": "external-operator-or-daytona-dashboard",
        "budget": {
            "monthlyCapDollars": config.budget_cap_dollars,
            "estimatedHours": config.expected_hours,
            "enforcedByScript": False,
            "note": "This is an operator cost estimate; Daytona billing enforcement is external.",
        },
        "createsOnlyOnExplicitApply": True,
    }


def _not_found(error: Exception) -> bool:
    text = str(error).lower()
    return "404" in text or "not found" in text or "does not exist" in text


def _preview_url(preview: Any) -> str:
    """Return only an origin/path; never print preview query tokens."""
    # Daytona 0.225 returns daytona_api_client.PortPreviewUrl, whose `url`
    # and `token` fields are both strings.  Accept a mapping for test doubles
    # and older adapters, but never stringify an opaque SDK object: its repr
    # may contain the private preview token.
    if isinstance(preview, str):
        value = preview
    elif isinstance(preview, Mapping):
        value = preview.get("url")
    else:
        value = getattr(preview, "url", None)
    if not isinstance(value, str):
        raise ProvisionError("Daytona returned an invalid preview URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
        raise ProvisionError("Daytona returned an invalid preview URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _state(sandbox: Any) -> str:
    value = getattr(sandbox, "state", "")
    return str(getattr(value, "value", value)).lower()


def _refresh_and_check_existing(sandbox: Any, config: Config) -> None:
    try:
        sandbox.refresh_data()
    except Exception as exc:
        raise ProvisionError("could not verify the existing sandbox configuration") from exc
    snapshot = getattr(sandbox, "snapshot", None)
    if str(snapshot or "") != config.snapshot:
        raise ProvisionError("existing sandbox uses a different snapshot; recreate it explicitly")
    env = getattr(sandbox, "env", None)
    if not isinstance(env, dict):
        raise ProvisionError("existing sandbox application environment could not be verified")
    missing = [name for name in APP_REQUIRED_ENV if not env.get(name)]
    if missing:
        raise ProvisionError("existing sandbox is missing required application environment; recreate it")
    if env.get("MAP_STUDIO_ORIGIN") != config.app_env.get("MAP_STUDIO_ORIGIN"):
        raise ProvisionError("existing sandbox origin differs; recreate it with the configured OAuth origin")
    if str(env.get("PORT", "")) != str(config.port):
        raise ProvisionError("existing sandbox port differs; recreate it with the configured application port")


def _ensure_healthy_state(daytona: Any, sandbox: Any, timeout: int) -> None:
    state = _state(sandbox)
    if state in {"error", "destroyed", "destroying", "deleting"}:
        raise ProvisionError(f"sandbox is in terminal state: {state}")
    if state not in {"started", "running", "ready"}:
        daytona.start(sandbox, timeout=timeout)


def _sdk_client() -> Any:
    try:
        from daytona import Daytona, DaytonaConfig
    except ImportError as exc:  # pragma: no cover - exercised by operator environment
        raise ProvisionError("install requirements-daytona.txt in the isolated SDK environment") from exc
    api_url = os.getenv("DAYTONA_API_URL")
    config = DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"], api_url=api_url) if api_url else DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"])
    return Daytona(config)


def _run(config: Config) -> dict[str, Any]:
    from daytona import CreateSandboxFromSnapshotParams

    daytona = _sdk_client()
    try:
        sandbox = daytona.get(config.name, request_timeout=config.start_timeout)
        created = False
    except Exception as exc:
        if not _not_found(exc):
            raise ProvisionError("could not inspect the named Daytona sandbox") from exc
        params = CreateSandboxFromSnapshotParams(
            snapshot=config.snapshot,
            name=config.name,
            labels={"app": "neighborhood-map-studio", "managed-by": "map-studio-provision"},
            public=config.public_transport,
            auto_stop_interval=config.autostop_minutes,
            env_vars={key: value for key, value in config.app_env.items() if key in APP_ENV_ALLOWLIST},
        )
        sandbox = daytona.create(params, timeout=config.start_timeout)
        created = True
    if not created:
        _refresh_and_check_existing(sandbox, config)

    # Keep the named sandbox's transport and idle policy aligned on every
    # operator run, including after an explicit private/public transition.
    sandbox.set_public(config.public_transport, request_timeout=config.start_timeout)
    sandbox.set_autostop_interval(config.autostop_minutes, request_timeout=config.start_timeout)
    # Explicitly starting a stopped/paused sandbox makes the restart path
    # deterministic after Daytona auto-stop. Terminal failures never wake.
    _ensure_healthy_state(daytona, sandbox, config.start_timeout)
    health = sandbox.process.exec(_health_command(config.port), timeout=HEALTH_TIMEOUT_SECONDS)
    exit_code = getattr(health, "exit_code", 0)
    if exit_code not in (None, 0):
        raise ProvisionError("sandbox started but Map Studio health check failed")
    preview = sandbox.get_preview_link(config.port, request_timeout=config.start_timeout)
    return {
        "operation": "created" if created else "restarted",
        "sandbox": config.name,
        "previewUrl": _preview_url(preview),
        "transport": "public-preview" if config.public_transport else "private-preview",
        "health": "ok",
        "autoStopMinutes": config.autostop_minutes,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--apply", action="store_true", help="perform the Daytona operation; dry-run is the default")
    result.add_argument("--public-transport", action="store_true", help="opt into a public Daytona preview after app auth is configured")
    result.add_argument("--snapshot", help="pinned Daytona snapshot name (or DAYTONA_MAP_STUDIO_SNAPSHOT)")
    result.add_argument("--name", default=SANDBOX_NAME)
    result.add_argument("--port", type=int, default=DEFAULT_PORT)
    result.add_argument("--autostop-minutes", type=int, default=DEFAULT_AUTOSTOP_MINUTES)
    result.add_argument("--start-timeout", type=int, default=DEFAULT_COLD_START_TIMEOUT)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = _config(args)
        result = _run(config) if args.apply else _plan(config, apply=False)
    except ProvisionError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except Exception:
        # SDK validation/HTTP exceptions may include request environment values.
        print(json.dumps({"error": "Daytona operation failed; check provider status and secure configuration."}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
