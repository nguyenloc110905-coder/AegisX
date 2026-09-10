import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from aegisx_launcher.state import LauncherAlreadyRunningError, LauncherState, LauncherStateError


def test_state_is_private_and_records_current_owner(tmp_path: Path) -> None:
    path = tmp_path / "state" / "launcher.json"
    state = LauncherState(path, pid=4321, instance_id="instance-a", pid_is_alive=lambda _: False)

    state.acquire()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"instance_id": "instance-a", "pid": 4321}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_live_existing_owner_rejects_duplicate_launcher(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    path.write_text('{"pid": 77, "instance_id": "live"}', encoding="utf-8")
    state = LauncherState(path, pid=88, instance_id="new", pid_is_alive=lambda pid: pid == 77)

    with pytest.raises(LauncherAlreadyRunningError, match="PID 77"):
        state.acquire()

    assert json.loads(path.read_text(encoding="utf-8"))["instance_id"] == "live"


def test_stale_owner_is_replaced_atomically(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    path.write_text('{"pid": 77, "instance_id": "stale"}', encoding="utf-8")
    state = LauncherState(path, pid=88, instance_id="new", pid_is_alive=lambda _: False)

    state.acquire()

    assert json.loads(path.read_text(encoding="utf-8")) == {"instance_id": "new", "pid": 88}


def test_malformed_existing_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    path.write_text("not-json", encoding="utf-8")
    state = LauncherState(path, pid=88, instance_id="new", pid_is_alive=lambda _: False)

    with pytest.raises(LauncherStateError, match="malformed"):
        state.acquire()

    assert path.read_text(encoding="utf-8") == "not-json"


def test_release_does_not_remove_state_owned_by_another_instance(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    first = LauncherState(path, pid=1, instance_id="first", pid_is_alive=lambda _: False)
    first.acquire()
    path.write_text('{"pid": 2, "instance_id": "second"}', encoding="utf-8")

    first.release()

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["instance_id"] == "second"


def test_context_manager_removes_its_own_state(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    state = LauncherState(path, pid=1, instance_id="only", pid_is_alive=lambda _: False)

    with state:
        assert path.exists()

    assert not path.exists()


def test_installer_invokes_uv_tool_install_with_absolute_launcher_path(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    installer = repository / "scripts" / "install-aegisx"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    args_file = tmp_path / "args"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$AEGISX_TEST_ARGS"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["AEGISX_TEST_ARGS"] = str(args_file)

    completed = subprocess.run(  # noqa: S603
        (str(installer),),
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "tool",
        "install",
        "--editable",
        str(repository / "tools" / "launcher"),
        "--force",
    ]
