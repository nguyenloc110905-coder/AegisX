from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migration_head_is_single_and_named() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))

    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0005_incident_foundation"]
