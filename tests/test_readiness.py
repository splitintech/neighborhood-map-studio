from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from server.map_studio.config import Settings, settings
from server.map_studio import main


def configure(monkeypatch):
    for name, value in {'origin': 'https://studio.example', 'github_client_id': 'client',
                        'github_client_secret': 'private-test-value', 'session_secret': 's' * 40,
                        'supabase_url': 'https://db.example', 'supabase_service_role_key': 'private-role'}.items():
        monkeypatch.setattr(settings, name, value)


def test_readiness_never_confuses_liveness_with_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'DIST', tmp_path)
    monkeypatch.setattr(settings, 'github_client_secret', '')
    client = TestClient(main.app)
    assert client.get('/healthz').status_code == 200
    response = client.get('/readyz')
    assert response.status_code == 503 and response.json()['ready'] is False
    assert response.headers['cache-control'] == 'private, no-store'
    configure(monkeypatch)
    assert client.get('/readyz').status_code == 503
    (tmp_path / 'index.html').write_text('<html></html>')
    response = client.get('/readyz')
    assert response.status_code == 200 and response.json()['ready'] is True
    assert 'private-role' not in response.text and 'private-test-value' not in response.text


def test_readiness_rejects_whitespace_configuration(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(main, 'DIST', tmp_path)
    (tmp_path / 'index.html').write_text('built')
    monkeypatch.setattr(settings, 'session_secret', ' ' * 40)
    assert TestClient(main.app).get('/readyz').status_code == 503


@pytest.mark.parametrize('value', ['/etc', '../server', 'server', 'frontend/../../server', ''])
def test_frontend_directory_cannot_expose_server_files(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, frontend_dir=value)


def test_http_loopback_requires_explicit_local_environment():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, origin='http://127.0.0.1:3000')
    assert Settings(_env_file=None, environment='development', origin='http://127.0.0.1:3000').origin
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment='development', origin='http://external.example')


def test_packaging_has_readiness_and_no_runtime_credentials():
    root = Path(__file__).resolve().parents[1]
    docker = (root / 'Dockerfile').read_text()
    assert 'USER studio' in docker and 'HEALTHCHECK' in docker and '/readyz' in docker
    assert 'COPY . ' not in docker and 'DAYTONA_API_KEY' not in docker
    assert 'COPY --from=frontend-build /src/frontend/dist ./frontend/dist' in docker


@pytest.mark.parametrize('kwargs', [
    {'origin': 'http://127.0.0.1:3000'},
    {'origin': 'https://user:never-log-url-password@example.com'},
    {'frontend_dir': '/etc'},
])
def test_configuration_validation_errors_redact_supplied_values(kwargs):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, github_client_secret='never-log-client-secret',
                 supabase_service_role_key='never-log-service-key', **kwargs)
    message = str(caught.value)
    assert 'never-log' not in message


def test_container_smoke_workflow_is_network_isolated_and_has_no_provider_secrets():
    workflow = Path(__file__).resolve().parents[1] / '.github/workflows/neighborhood-map-studio.yml'
    text = workflow.read_text()
    smoke = text.split('      - name: Offline release-container readiness and access boundary', 1)[1]
    assert '--network none' in smoke
    assert '${{ secrets.' not in smoke
    assert 'MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED=false' in smoke
    assert '/readyz' in smoke and '401' in smoke and '404' in smoke
