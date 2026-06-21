import pytest


@pytest.fixture
def enable_summarizer(monkeypatch):
    """Force the summarizer on regardless of env."""
    from backend import config
    monkeypatch.setattr(config, "SUMMARIZER_ENABLED", True)
    monkeypatch.setattr(config, "SUMMARIZER_MODEL", "test/model")
    return config
