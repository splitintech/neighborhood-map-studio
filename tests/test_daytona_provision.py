from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_provision_is_dry_run_and_private_by_default(capsys):
    module = load_script("daytona-provision.py")
    assert module.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "dry-run"
    assert result["transport"] == "private-preview"
    assert result["createsOnlyOnExplicitApply"] is True
    assert result["budget"]["enforcedByScript"] is False
    assert result["budget"]["monthlyCapDollars"] == 100
    assert result["budget"]["estimatedHours"] == 200
    assert result["coldStartTimeoutSeconds"] == 60


def test_public_transport_requires_explicit_auth_configuration(monkeypatch):
    module = load_script("daytona-provision.py")
    monkeypatch.delenv("MAP_STUDIO_PUBLIC_TRANSPORT_AUTH_CONFIGURED", raising=False)
    assert module.main(["--public-transport"]) == 2


def test_runtime_port_is_fixed_to_three_thousand():
    module = load_script("daytona-provision.py")
    assert module.main(["--port", "4181"]) == 2


def test_apply_requires_server_key_and_snapshot(monkeypatch):
    module = load_script("daytona-provision.py")
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.delenv("DAYTONA_MAP_STUDIO_SNAPSHOT", raising=False)
    assert module.main(["--apply"]) == 2


def test_apply_requires_all_server_only_app_environment(monkeypatch):
    module = load_script("daytona-provision.py")
    monkeypatch.setenv("DAYTONA_API_KEY", "daytona-control-plane-secret")
    monkeypatch.setenv("DAYTONA_MAP_STUDIO_SNAPSHOT", "map-studio-release")
    for name in module.APP_REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    assert module.main(["--apply"]) == 2


def test_snapshot_requires_digest_pinned_image():
    module = load_script("create-snapshot.py")
    assert module.main(["--name", "map-studio", "--image", "ghcr.io/acme/map:release"]) == 2
    assert module.main(["--name", "map-studio", "--image", "ghcr.io/acme/map@sha256:" + "a" * 64]) == 0
    assert module.main(["--name", "map_studio", "--image", "ghcr.io/acme/map@sha256:" + "a" * 64]) == 2
    assert module.main(["--name", "map-studio", "--image", "ghcr.io/acme/map@sha256:abc"]) == 2


def test_runtime_files_have_fixed_port_and_no_secret_copy():
    dockerfile = (ROOT / "Dockerfile").read_text()
    start = (ROOT / "start.sh").read_text()
    assert "uvicorn server.map_studio.main:app" in start
    assert "--port \"$PORT\"" in start
    assert "EXPOSE 3000" in dockerfile
    assert "DAYTONA_API_KEY" not in dockerfile


def test_apply_lifecycle_reuses_named_sandbox_and_runs_fixed_health_check(monkeypatch):
    module = load_script("daytona-provision.py")
    calls = []

    class FakeSandbox:
        name = "neighborhood-map-studio-runtime"
        state = "stopped"
        snapshot = "pinned"
        env = {"MAP_STUDIO_ORIGIN": "https://studio.example", "PORT": "3000", **{name: "configured" for name in (
            "MAP_STUDIO_GITHUB_CLIENT_ID", "MAP_STUDIO_GITHUB_CLIENT_SECRET", "MAP_STUDIO_SESSION_SECRET",
            "MAP_STUDIO_SUPABASE_URL", "MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY",
        )}}

        class Process:
            def exec(self, command, timeout):
                calls.append(("health", command, timeout))
                return SimpleNamespace(exit_code=0)

        process = Process()

        def refresh_data(self):
            calls.append(("refresh",))
            return self

        def set_public(self, value, request_timeout):
            calls.append(("public", value, request_timeout))

        def set_autostop_interval(self, value, request_timeout):
            calls.append(("autostop", value, request_timeout))

        def get_preview_link(self, port, request_timeout):
            calls.append(("preview", port, request_timeout))
            return SimpleNamespace(url="https://preview.example/app?token=do-not-print#fragment")

    class FakeDaytona:
        def __init__(self, config):
            calls.append(("client", config.api_key))

        def get(self, name, request_timeout):
            calls.append(("get", name, request_timeout))
            return FakeSandbox()

        def create(self, params, timeout):
            calls.append(("create", params.name, params.snapshot, params.public, params.env_vars, timeout))
            return FakeSandbox()

        def start(self, sandbox, timeout):
            calls.append(("start", timeout))

    class FakeConfig:
        def __init__(self, api_key, api_url=None):
            self.api_key = api_key

    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(
        Daytona=FakeDaytona,
        DaytonaConfig=FakeConfig,
        CreateSandboxFromSnapshotParams=lambda **kwargs: SimpleNamespace(**kwargs),
    ))
    monkeypatch.setenv("DAYTONA_API_KEY", "server-secret")
    config = module.Config("neighborhood-map-studio-runtime", "pinned", False, 3000, 15, 60, 100, 200, {
        "MAP_STUDIO_ORIGIN": "https://studio.example", "MAP_STUDIO_GITHUB_CLIENT_ID": "client-id",
        "MAP_STUDIO_GITHUB_CLIENT_SECRET": "client-secret", "MAP_STUDIO_SESSION_SECRET": "session-secret",
        "MAP_STUDIO_SUPABASE_URL": "https://project.supabase.co", "MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "PORT": "3000",
    })
    result = module._run(config)
    assert result["health"] == "ok"
    assert ("refresh",) in calls
    assert any(item[0] == "health" and ":3000/healthz" in item[1] and item[2] == 10 for item in calls)
    assert ("public", False, 60) in calls
    assert ("autostop", 15, 60) in calls
    assert ("preview", 3000, 60) in calls
    assert result["previewUrl"] == "https://preview.example/app"
    assert not any(item[0] == "create" for item in calls)
    assert all("server-secret" not in json.dumps(item) for item in calls if item[0] != "client")


def test_new_sandbox_forwards_only_allowlisted_application_environment(monkeypatch):
    module = load_script("daytona-provision.py")
    calls = []

    class Params:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Sandbox:
        state = "started"
        snapshot = "pinned"
        env = {}

        class Process:
            def exec(self, command, timeout):
                return SimpleNamespace(exit_code=0)

        process = Process()

        def set_public(self, value, request_timeout): pass
        def set_autostop_interval(self, value, request_timeout): pass
        def get_preview_link(self, port, request_timeout): return "https://preview.example/app?token=secret"

    class Daytona:
        def __init__(self, config): pass
        def get(self, name, request_timeout): raise RuntimeError("404 not found")
        def create(self, params, timeout): calls.append(params); return Sandbox()

    class Config:
        def __init__(self, **kwargs): pass

    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(
        Daytona=Daytona, DaytonaConfig=Config, CreateSandboxFromSnapshotParams=Params,
    ))
    monkeypatch.setenv("DAYTONA_API_KEY", "control-plane-secret")
    app_env = {name: "value" for name in module.APP_REQUIRED_ENV} | {"PORT": "3000", "MAP_STUDIO_UNKNOWN": "must-not-forward"}
    config = module.Config("neighborhood-map-studio-runtime", "pinned", False, 3000, 15, 60, 100, 200, app_env)
    result = module._run(config)
    forwarded = calls[0].env_vars
    assert "MAP_STUDIO_UNKNOWN" not in forwarded
    assert forwarded["PORT"] == "3000"
    assert result["previewUrl"] == "https://preview.example/app"


def test_preview_mapping_redacts_token_without_stringifying_sdk_object():
    module = load_script("daytona-provision.py")

    class OpaquePreview:
        def __str__(self):
            return "OpaquePreview(token=private-secret)"

    assert module._preview_url({"url": "https://preview.example/app?token=private-secret"}) == "https://preview.example/app"
    with pytest.raises(module.ProvisionError):
        module._preview_url(OpaquePreview())


def test_snapshot_apply_uses_one_cpu_one_gib_and_pinned_sdk_shape(monkeypatch):
    module = load_script("create-snapshot.py")
    calls = []

    class Params:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class Resources:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class SnapshotService:
        def create(self, params): calls.append(params); return SimpleNamespace(id="snapshot-id")

    class Daytona:
        def __init__(self, config): self.snapshot = SnapshotService()

    class Config:
        def __init__(self, **kwargs): pass

    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(
        CreateSnapshotParams=Params, Resources=Resources, Daytona=Daytona, DaytonaConfig=Config,
    ))
    monkeypatch.setenv("DAYTONA_API_KEY", "control-plane-secret")
    result = module._apply("map-studio", "ghcr.io/acme/map@sha256:" + "b" * 64, ["/opt/map-studio/start.sh"])
    assert result["snapshot"] == "snapshot-id"
    assert calls[0].resources.cpu == 1 and calls[0].resources.memory == 1
    assert calls[0].entrypoint == ["/opt/map-studio/start.sh"]
