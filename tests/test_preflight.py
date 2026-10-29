import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preflight', ROOT / 'scripts/preflight.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_preflight_missing_then_complete_inventory(tmp_path):
    result, code = module.inspect(tmp_path)
    assert code == 2 and result['networkRequests'] == result['databaseWrites'] == 0
    (tmp_path / 'frontend/dist').mkdir(parents=True)
    (tmp_path / 'frontend/dist/index.html').write_text('built')
    (tmp_path / 'migrations').mkdir()
    for name in module.MIGRATIONS:
        (tmp_path / 'migrations' / name).write_text('-- fixture')
    result, code = module.inspect(tmp_path)
    assert code == 0 and result['localReady'] is True
    assert result['remoteReadinessVerified'] is False
    assert all(len(m['sha256']) == 64 for m in result['migrations'])


def test_invalid_configuration_never_prints_sensitive_input(tmp_path, monkeypatch):
    monkeypatch.setenv('MAP_STUDIO_ORIGIN', 'https://user:never-print-password@example.com')
    result, code = module.inspect(tmp_path, require_config=True)
    assert code == 2 and result['configurationError'] == 'invalid_configuration'
    assert 'never-print-password' not in str(result)
