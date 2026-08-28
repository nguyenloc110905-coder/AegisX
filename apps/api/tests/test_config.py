from aegisx_api.config import Settings


def test_settings_read_aegisx_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("AEGISX_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AEGISX_DATABASE_URL", "sqlite+aiosqlite:///test.db")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.database_url == "sqlite+aiosqlite:///test.db"


def test_settings_reject_unknown_environment_name() -> None:
    try:
        Settings(_env_file=None, environment="stagingg")
    except ValueError as error:
        assert "environment" in str(error)
    else:
        raise AssertionError("invalid environment must be rejected")
