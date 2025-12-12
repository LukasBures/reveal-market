from shared.env_presets import get_preset, resolve_mode


def test_local_preset_contains_docker_hosts(monkeypatch):
    monkeypatch.setenv("RM_ENVIRONMENT", "local")
    preset = get_preset()
    assert "api" in preset["api_allowed_hosts"]
    assert "api:8000" in preset["api_allowed_hosts"]
    assert "testserver" in preset["api_allowed_hosts"]


def test_prod_preset_defaults(monkeypatch):
    monkeypatch.setenv("RM_ENVIRONMENT", "prod")
    preset = get_preset()
    assert preset["api_host"] == "0.0.0.0"  # noqa: S104
    assert "https://stream.revealmarket.xyz" in preset["streamer_public"]


def test_resolve_mode_prefers_prod_when_set(monkeypatch):
    monkeypatch.setenv("RM_ENVIRONMENT", "production")
    assert resolve_mode() == "prod"
    monkeypatch.setenv("RM_ENVIRONMENT", "local")
    assert resolve_mode() == "local"


def test_resolve_mode_uses_environment(monkeypatch):
    monkeypatch.delenv("RM_ENVIRONMENT", raising=False)
    monkeypatch.setenv("RM_ENVIRONMENT", "production")
    assert resolve_mode() == "prod"
    monkeypatch.setenv("RM_ENVIRONMENT", "local")
    assert resolve_mode() == "local"
