from fastapi.testclient import TestClient
import pytest
from server.map_studio.main import app
from server.map_studio.config import settings

client = TestClient(app)

@pytest.mark.parametrize('method,path,body', [
    ('GET', '/api/bff/map-studio/projects', None),
    ('GET', '/api/bff/map-studio/projects/san-francisco-mission', None),
    ('GET', '/api/bff/map-studio/projects/san-francisco-mission/assets', None),
    ('GET', '/api/bff/map-studio/projects/san-francisco-mission/versions', None),
    ('POST', '/api/bff/map-studio/projects/san-francisco-mission/lease', {'clientId': 'test-tab'}),
    ('POST', '/api/bff/map-studio/projects/san-francisco-mission/publish', {'clientId': 'test-tab', 'expectedRevision': 0}),
    ('POST', '/api/bff/map-studio/projects/san-francisco-mission/assets', {}),
    ('GET', '/api/runtime-info', None),
])
def test_private_http_routes_reject_unauthenticated_requests(method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_no_auth_config_fails_closed_and_public_manifest_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'github_client_secret', '')
    monkeypatch.setattr(settings, 'public_manifests_enabled', False)
    assert client.get('/api/auth/login').status_code == 503
    assert client.get('/api/public/map-studio/san-francisco-mission').status_code == 404
    assert client.get('/healthz').json()['ok'] is True
    assert client.get('/openapi.json').status_code == 404


def test_large_request_rejected_before_model_decoding():
    response = client.post('/api/bff/map-studio/projects/san-francisco-mission/draft', content=b'x'*(2*1024*1024+1))
    assert response.status_code == 413
