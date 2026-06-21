from backend import config


def test_summarizer_defaults_present():
    assert isinstance(config.SUMMARIZER_MODEL, str) and config.SUMMARIZER_MODEL
    assert isinstance(config.SUMMARIZER_ENABLED, bool)
    assert isinstance(config.SUMMARIZER_VERSION, int)
    assert config.SUMMARIZER_MIN_CHARS > 0
