import pytest

from shopchat.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://app@localhost/db",
        database_owner_url="postgresql+asyncpg://owner@localhost/db",
        redis_url="redis://localhost:6379/0",
        app_url="https://example.test",
    )


def test_llm_calls_are_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_CALLS_ENABLED", raising=False)
    assert _settings().llm_calls_enabled is False


def test_voice_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    assert _settings().voice_enabled is False


def test_secrets_are_hidden_when_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")
    assert "sk-should-not-appear" not in repr(_settings())


def test_dev_mode_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    assert _settings().dev_mode is False


def test_dev_mode_uses_the_seeded_store_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_SHOP_DOMAIN", raising=False)
    assert _settings().dev_shop_domain == "cosmo-genie.myshopify.com"
