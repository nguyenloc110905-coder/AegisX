import stat
from pathlib import Path
from uuid import UUID

from aegisx_agent.identity import load_or_create_identity


def test_identity_is_stable_and_private(tmp_path: Path) -> None:
    identity_path = tmp_path / "device.json"

    first = load_or_create_identity(identity_path)
    second = load_or_create_identity(identity_path)

    assert first == second
    assert UUID(first.external_id)
    assert stat.S_IMODE(identity_path.stat().st_mode) == 0o600
