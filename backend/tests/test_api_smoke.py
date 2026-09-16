import pytest
from pydantic import ValidationError

from src.config.settings import DEFAULT_ENCRYPTION_KEY, Settings, get_settings


@pytest.mark.asyncio
async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "app" in body


@pytest.mark.asyncio
async def test_public_settings_database_types(client):
    response = await client.get("/api/settings/public")
    assert response.status_code == 200
    body = response.json()
    assert body["database_types"] == ["postgresql"]


def test_settings_reject_default_encryption_key_when_not_debug(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", DEFAULT_ENCRYPTION_KEY)
    with pytest.raises(ValidationError):
        Settings()
    get_settings.cache_clear()


def test_settings_accept_custom_encryption_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", "a-unique-production-style-secret-key")
    settings = Settings()
    assert settings.encryption_key == "a-unique-production-style-secret-key"
    get_settings.cache_clear()
