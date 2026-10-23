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

        def refresh_data(self, request_timeout):
            calls.append(("refresh", request_timeout))
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
        "MAP_STUDIO_ORIGIN": "https://studio.example", "MAP_STUDIO_GITHUB_CLIENT_ID": "configured",
        "MAP_STUDIO_GITHUB_CLIENT_SECRET": "configured", "MAP_STUDIO_SESSION_SECRET": "configured",
        "MAP_STUDIO_SUPABASE_URL": "configured", "MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY": "configured",
        "PORT": "3000",
    })
    result = module._run(config)
    assert result["health"] == "ok"
    assert ("refresh", 60) in calls
    assert any(item[0] == "health" and ":3000/readyz" in item[1] and item[2] == 10 for item in calls)
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
        def get(self, name, request_timeout):
            error = RuntimeError("404 not found")
            error.status_code = 404
            raise error
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
        def create(self, params, timeout):
            assert timeout == 600
            calls.append(params)
            return SimpleNamespace(id="snapshot-id")

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


def provision_config(module, **overrides):
    values = dict(name=module.SANDBOX_NAME, snapshot="pinned", public_transport=False,
                  port=3000, autostop_minutes=15, start_timeout=3,
                  budget_cap_dollars=100, expected_hours=200,
                  app_env={name: "configured" for name in module.APP_REQUIRED_ENV} | {"PORT": "3000"})
    return module.Config(**(values | overrides))


def fake_clock(monkeypatch, module):
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    return now


def test_readiness_retries_startup_race(monkeypatch):
    module = load_script("daytona-provision.py")
    now = fake_clock(monkeypatch, module)
    results = iter([RuntimeError("toolbox unavailable"), SimpleNamespace(exit_code=1), SimpleNamespace(exit_code=0)])
    commands = []
    def execute(command, timeout):
        commands.append((command, timeout))
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result
    module._wait_for_readiness(SimpleNamespace(process=SimpleNamespace(exec=execute)), provision_config(module))
    assert now[0] == 2
    assert len(commands) == 3
    assert all("/readyz" in command for command, _ in commands)
    assert [timeout for _, timeout in commands] == [3, 2, 1]


@pytest.mark.parametrize("result", [SimpleNamespace(), SimpleNamespace(exit_code=None), SimpleNamespace(exit_code=False), SimpleNamespace(exit_code=1)])
def test_readiness_fails_closed_with_bounded_timeout(monkeypatch, result):
    module = load_script("daytona-provision.py")
    now = fake_clock(monkeypatch, module)
    sandbox = SimpleNamespace(process=SimpleNamespace(exec=lambda command, timeout: result))
    with pytest.raises(module.ProvisionError, match="readiness timed out"):
        module._wait_for_readiness(sandbox, provision_config(module))
    assert now[0] == 3


@pytest.mark.parametrize("name,value", [("MAP_STUDIO_GITHUB_CLIENT_SECRET", "changed"), ("MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED", "1"), ("PORT", "3001")])
def test_existing_sandbox_rejects_environment_drift_without_disclosing_values(name, value):
    module = load_script("daytona-provision.py")
    config = provision_config(module)
    sandbox = SimpleNamespace(snapshot="pinned", env=config.app_env | {name: value}, refresh_data=lambda request_timeout: None)
    with pytest.raises(module.ProvisionError, match="environment differs") as error:
        module._refresh_and_check_existing(sandbox, config)
    assert value not in str(error.value)


def test_not_found_requires_structured_status():
    module = load_script("daytona-provision.py")
    for text in ("404", "not found", "does not exist", "request 404 authentication failed"):
        assert not module._not_found(RuntimeError(text))
    error = RuntimeError("opaque response")
    error.status_code = 404
    assert module._not_found(error)
    error.status_code = 403
    assert not module._not_found(error)


@pytest.mark.parametrize("state", ["", "stopping", "destroyed", "error", "resizing"])
def test_unsafe_states_do_not_start(state):
    module = load_script("daytona-provision.py")
    def unexpected_start(*args, **kwargs):
        pytest.fail("must not start an unknown, busy, or terminal sandbox")
    with pytest.raises(module.ProvisionError):
        module._ensure_healthy_state(SimpleNamespace(start=unexpected_start), SimpleNamespace(state=state), 3)


def test_starting_state_waits_without_duplicate_start():
    module = load_script("daytona-provision.py")
    calls = []
    sandbox = SimpleNamespace(state="starting", wait_for_sandbox_start=lambda timeout: calls.append(timeout))
    module._ensure_healthy_state(SimpleNamespace(), sandbox, 3)
    assert calls == [3]


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_snapshot_rejects_unbounded_timeout(timeout):
    module = load_script("create-snapshot.py")
    assert module.main(["--name", "map-studio", "--image", "ghcr.io/acme/map@sha256:" + "a" * 64, "--timeout", timeout]) == 2


@pytest.mark.parametrize("ready", [True, False])
def test_public_transport_only_enabled_after_readiness(monkeypatch, ready):
    module = load_script("daytona-provision.py")
    calls = []
    class Sandbox:
        state = "started"
        def set_public(self, value, request_timeout): calls.append(("public", value))
        def set_autostop_interval(self, value, request_timeout): pass
        def get_preview_link(self, port, request_timeout):
            calls.append(("preview",))
            return "https://preview.example"
    class Client:
        def get(self, name, request_timeout):
            error = RuntimeError("missing")
            error.status_code = 404
            raise error
        def create(self, params, timeout):
            calls.append(("create-public", params.public))
            return Sandbox()
    def readiness(sandbox, config):
        calls.append(("ready", ready))
        if not ready:
            raise module.ProvisionError("not ready")
    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(CreateSandboxFromSnapshotParams=lambda **kwargs: SimpleNamespace(**kwargs)))
    monkeypatch.setattr(module, "_sdk_client", lambda: Client())
    monkeypatch.setattr(module, "_wait_for_readiness", readiness)
    config = provision_config(module, public_transport=True)
    if ready:
        module._run(config)
        assert calls == [("create-public", False), ("public", False), ("ready", True), ("public", True), ("preview",)]
    else:
        with pytest.raises(module.ProvisionError):
            module._run(config)
        assert calls == [("create-public", False), ("public", False), ("ready", False)]


def test_lookup_error_does_not_create_sandbox(monkeypatch):
    module = load_script("daytona-provision.py")
    class Client:
        def get(self, name, request_timeout): raise RuntimeError("request 404 failed authentication")
        def create(self, *args, **kwargs): pytest.fail("an unrelated failure must not create a sandbox")
    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(CreateSandboxFromSnapshotParams=lambda **kwargs: None))
    monkeypatch.setattr(module, "_sdk_client", lambda: Client())
    with pytest.raises(module.ProvisionError, match="could not inspect"):
        module._run(provision_config(module))


def set_valid_app_environment(monkeypatch, module):
    for name in module.APP_REQUIRED_ENV:
        monkeypatch.setenv(name, "configured")
    monkeypatch.setenv("MAP_STUDIO_ORIGIN", "https://studio.example")
    monkeypatch.setenv("MAP_STUDIO_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("MAP_STUDIO_SESSION_SECRET", "s" * 32)
    for name in module.APP_OPTIONAL_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", [
    "MAP_STUDIO_GITHUB_CLIENT_ID", "MAP_STUDIO_GITHUB_CLIENT_SECRET",
    "MAP_STUDIO_SESSION_SECRET", "MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY",
    "MAP_STUDIO_ORIGIN", "MAP_STUDIO_SUPABASE_URL",
])
def test_required_app_values_must_not_be_blank(monkeypatch, name):
    module = load_script("daytona-provision.py")
    set_valid_app_environment(monkeypatch, module)
    monkeypatch.setenv(name, " \t\n ")
    with pytest.raises(module.ProvisionError, match="missing required"):
        module._app_environment(3000, required=True)


def test_session_secret_minimum_excludes_padding(monkeypatch):
    module = load_script("daytona-provision.py")
    set_valid_app_environment(monkeypatch, module)
    monkeypatch.setenv("MAP_STUDIO_SESSION_SECRET", " " * 20 + "s" * 20)
    with pytest.raises(module.ProvisionError, match="at least 32"):
        module._app_environment(3000, required=True)


@pytest.mark.parametrize("name,value", [
    ("MAP_STUDIO_ENVIRONMENT", "prod"), ("MAP_STUDIO_ENVIRONMENT", ""),
    ("MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED", "maybe"), ("MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED", ""),
    ("MAP_STUDIO_SESSION_HOURS", "0"), ("MAP_STUDIO_SESSION_HOURS", "9"),
    ("MAP_STUDIO_SESSION_HOURS", "1.5"), ("MAP_STUDIO_SESSION_HOURS", "1_0"),
    ("MAP_STUDIO_SESSION_HOURS", ""),
])
def test_invalid_optional_config_is_rejected_before_apply(monkeypatch, name, value):
    module = load_script("daytona-provision.py")
    set_valid_app_environment(monkeypatch, module)
    monkeypatch.setenv("DAYTONA_API_KEY", "test-control-key")
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(module, "_run", lambda config: pytest.fail("must reject config before provider work"))
    assert module.main(["--apply", "--snapshot", "pinned"]) == 2


@pytest.mark.parametrize("environment,boolean,hours", [
    ("production", "true", "1"), ("development", "false", "8"), ("test", "YES", "4"),
])
def test_valid_optional_app_config(monkeypatch, environment, boolean, hours):
    module = load_script("daytona-provision.py")
    set_valid_app_environment(monkeypatch, module)
    monkeypatch.setenv("MAP_STUDIO_ENVIRONMENT", environment)
    monkeypatch.setenv("MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED", boolean)
    monkeypatch.setenv("MAP_STUDIO_SESSION_HOURS", hours)
    assert module._app_environment(3000, required=True)["MAP_STUDIO_SESSION_HOURS"] == hours


@pytest.mark.parametrize("script", ["daytona-provision.py", "create-snapshot.py"])
@pytest.mark.parametrize("url", [
    "http://api.example/api", "https://user:secret@api.example/api", "https://@api.example/api",
    "https://api.example/api?token=secret", "https://api.example/api#secret", "https://api.example/api?",
    "https://api.example/api#", "https://api.example:bad/api", "https://api.example:65536/api",
    "https://api.example:0/api", "https://api.example/\napi", "https://api.example\\evil/api", "", "api.example/api",
])
def test_control_plane_url_rejected_before_sdk_initialization(monkeypatch, script, url):
    module = load_script(script)
    monkeypatch.setenv("DAYTONA_API_URL", url)
    monkeypatch.setenv("DAYTONA_API_KEY", "test-control-key")
    monkeypatch.setitem(sys.modules, "daytona", SimpleNamespace(Daytona=lambda *args: pytest.fail("must not initialize SDK")))
    error = getattr(module, "ProvisionError", getattr(module, "SnapshotError", None))
    with pytest.raises(error, match="credential-free HTTPS"):
        if script == "daytona-provision.py":
            module._sdk_client()
        else:
            module._apply("pinned", "image", ["/opt/map-studio/start.sh"])


@pytest.mark.parametrize("script", ["daytona-provision.py", "create-snapshot.py"])
@pytest.mark.parametrize("url", ["https://app.daytona.io/api", "https://api.example:443/custom/api"])
def test_control_plane_url_allows_https_paths(monkeypatch, script, url):
    module = load_script(script)
    monkeypatch.setenv("DAYTONA_API_URL", url)
    assert module._api_url() == url
