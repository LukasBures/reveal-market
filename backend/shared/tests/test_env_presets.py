from shared.env_presets import PRESETS, get_preset, resolve_mode


def test_local_preset_contains_docker_hosts(monkeypatch):
    monkeypatch.setenv("MODE", "local")
    preset = get_preset()
    assert "api" in preset["api_allowed_hosts"]
    assert "api:8000" in preset["api_allowed_hosts"]
    assert "testserver" in preset["api_allowed_hosts"]


def test_prod_preset_defaults(monkeypatch):
    monkeypatch.setenv("MODE", "prod")
    preset = get_preset()
    assert preset["api_host"] == "0.0.0.0"
    assert "https://stream.revealmarket.xyz" in preset["streamer_public"]


def test_resolve_mode_prefers_prod_when_set(monkeypatch):
    monkeypatch.setenv("MODE", "production")
    assert resolve_mode() == "prod"
    monkeypatch.setenv("MODE", "local")
    assert resolve_mode() == "local"
