from pathlib import Path

import pytest

from aegisx_launcher.cli import main
from aegisx_launcher.project import ProjectDiscoveryError, find_project_root, select_env_file


def _make_project(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "compose.yaml").write_text("name: test\n", encoding="utf-8")
    api = path / "apps" / "api"
    api.mkdir(parents=True)
    (api / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    return path


def test_finds_project_by_walking_up_from_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "aegisx")
    nested = project / "docs" / "nested"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    monkeypatch.delenv("AEGISX_PROJECT_ROOT", raising=False)

    assert find_project_root() == project.resolve()


def test_explicit_project_root_overrides_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "explicit")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))

    assert find_project_root() == project.resolve()


def test_invalid_explicit_project_root_fails_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback = _make_project(tmp_path / "fallback")
    monkeypatch.chdir(fallback)
    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(tmp_path / "missing"))

    with pytest.raises(ProjectDiscoveryError, match="AEGISX_PROJECT_ROOT"):
        find_project_root()


def test_falls_back_to_editable_package_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "editable")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("AEGISX_PROJECT_ROOT", raising=False)
    monkeypatch.setattr("aegisx_launcher.project.PACKAGE_LOCATION", project / "tools")

    assert find_project_root() == project.resolve()


def test_env_file_prefers_dot_env_and_falls_back_to_example(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "aegisx")
    example = project / ".env.example"
    example.write_text("MODE=example\n", encoding="utf-8")

    assert select_env_file(project) == example

    local = project / ".env"
    local.write_text("MODE=local\n", encoding="utf-8")
    assert select_env_file(project) == local


def test_missing_environment_files_fails_clearly(tmp_path: Path) -> None:
    project = _make_project(tmp_path / "aegisx")

    with pytest.raises(ProjectDiscoveryError, match="environment file"):
        select_env_file(project)


def test_help_is_available_without_discovering_a_project(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    assert "Run the local AegisX development stack" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "expected_method", "expected_code"),
    [([], "run", 7), (["doctor"], "doctor", 8), (["stop"], "stop", 9)],
)
def test_cli_dispatches_to_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected_method: str,
    expected_code: int,
) -> None:
    project = _make_project(tmp_path / "aegisx")
    env_file = project / ".env.example"
    env_file.write_text("MODE=test\n", encoding="utf-8")
    called: list[str] = []

    class FakeRuntime:
        def __init__(self, root: Path, selected_env: Path) -> None:
            assert root == project
            assert selected_env == env_file

        def run(self, *, show_ui: bool = True) -> int:
            called.append("run")
            return 7

        def doctor(self) -> int:
            called.append("doctor")
            return 8

        def stop(self) -> int:
            called.append("stop")
            return 9

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)

    assert main(arguments) == expected_code
    assert called == [expected_method]


def test_cli_reports_project_discovery_failure_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGISX_PROJECT_ROOT", raising=False)
    monkeypatch.setattr("aegisx_launcher.project.PACKAGE_LOCATION", tmp_path)

    assert main(["doctor"]) == 2
    assert "Could not locate AegisX" in capsys.readouterr().err


def test_run_command_holds_single_instance_state_while_runtime_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    events: list[str] = []

    class FakeState:
        @classmethod
        def default(cls) -> "FakeState":
            return cls()

        def __enter__(self) -> "FakeState":
            events.append("state-enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("state-exit")

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def run(self, *, show_ui: bool = True) -> int:
            events.append(f"runtime-run:{show_ui}")
            return 0

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", FakeState)
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)

    assert main([]) == 0
    assert events == ["state-enter", "runtime-run:True", "state-exit"]


def test_run_no_ui_dispatches_log_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    selected: list[bool] = []

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def run(self, *, show_ui: bool = True) -> int:
            selected.append(show_ui)
            return 0

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)

    assert main(["run", "--no-ui"]) == 0
    assert selected == [False]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [(["data-status"], "data-status"), (["prune", "--dry-run"], "prune:False:False")],
)
def test_read_only_maintenance_commands_run_without_launcher_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: str,
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    calls: list[str] = []

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def data_status(self) -> int:
            calls.append("data-status")
            return 0

        def prune(self, *, apply: bool, confirmed: bool) -> int:
            calls.append(f"prune:{apply}:{confirmed}")
            return 0

    class ForbiddenState:
        @classmethod
        def default(cls) -> "ForbiddenState":
            raise AssertionError("read-only maintenance must not acquire the launcher lock")

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", ForbiddenState)

    assert main(arguments) == 0
    assert calls == [expected]


def test_prune_apply_holds_launcher_lock_and_forwards_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    events: list[str] = []

    class FakeState:
        @classmethod
        def default(cls) -> "FakeState":
            return cls()

        def __enter__(self) -> "FakeState":
            events.append("state-enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("state-exit")

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def prune(self, *, apply: bool, confirmed: bool) -> int:
            events.append(f"prune:{apply}:{confirmed}")
            return 0

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", FakeState)

    assert main(["prune", "--apply", "--yes"]) == 0
    assert events == ["state-enter", "prune:True:True", "state-exit"]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["local-data-status"], "status"),
        (["local-verify"], "verify"),
        (["local-prune", "--dry-run"], "prune:False:False"),
    ],
)
def test_read_only_local_commands_bypass_launcher_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: str,
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    calls: list[str] = []

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def local_data_status(self) -> int:
            calls.append("status")
            return 0

        def local_verify(self) -> int:
            calls.append("verify")
            return 0

        def local_prune(self, *, apply: bool, confirmed: bool) -> int:
            calls.append(f"prune:{apply}:{confirmed}")
            return 0

    class ForbiddenState:
        @classmethod
        def default(cls) -> "ForbiddenState":
            raise AssertionError("read-only local command must not acquire launcher lock")

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", ForbiddenState)

    assert main(arguments) == 0
    assert calls == [expected]


def test_local_prune_apply_requires_yes_before_runtime_or_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")

    class ForbiddenRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def local_prune(self, *, apply: bool, confirmed: bool) -> int:
            raise AssertionError("unsafe apply must be refused before runtime")

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", ForbiddenRuntime)

    assert main(["local-prune", "--apply"]) == 2


def test_local_prune_confirmed_apply_holds_launcher_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")
    events: list[str] = []

    class FakeState:
        @classmethod
        def default(cls) -> "FakeState":
            return cls()

        def __enter__(self) -> "FakeState":
            events.append("state-enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("state-exit")

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def local_prune(self, *, apply: bool, confirmed: bool) -> int:
            events.append(f"prune:{apply}:{confirmed}")
            return 0

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", FakeState)

    assert main(["local-prune", "--apply", "--yes"]) == 0
    assert events == ["state-enter", "prune:True:True", "state-exit"]


@pytest.mark.parametrize(
    ("arguments", "confirmed"),
    [(["dev-reset"], False), (["dev-reset", "--yes"], True)],
)
def test_dev_reset_dispatches_confirmation_while_holding_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    confirmed: bool,
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("AEGISX_ENV=development\n", encoding="utf-8")
    events: list[str] = []

    class FakeState:
        @classmethod
        def default(cls) -> "FakeState":
            return cls()

        def __enter__(self) -> "FakeState":
            events.append("state-enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("state-exit")

    class FakeRuntime:
        def __init__(self, _root: Path, _env: Path) -> None:
            pass

        def dev_reset(self, *, confirmed: bool) -> int:
            events.append(f"dev-reset:{confirmed}")
            return 0

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", FakeState)
    monkeypatch.setattr("aegisx_launcher.cli.AegisXRuntime", FakeRuntime)

    assert main(arguments) == 0
    assert events == ["state-enter", f"dev-reset:{confirmed}", "state-exit"]


@pytest.mark.parametrize("arguments", [[], ["dev-reset", "--yes"]])
def test_duplicate_launcher_is_reported_without_starting_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    project = _make_project(tmp_path / "aegisx")
    (project / ".env.example").write_text("MODE=test\n", encoding="utf-8")

    class RejectingState:
        @classmethod
        def default(cls) -> "RejectingState":
            return cls()

        def __enter__(self) -> "RejectingState":
            from aegisx_launcher.state import LauncherAlreadyRunningError

            raise LauncherAlreadyRunningError("already active")

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setenv("AEGISX_PROJECT_ROOT", str(project))
    monkeypatch.setattr("aegisx_launcher.cli.LauncherState", RejectingState)

    assert main(arguments) == 3
    assert "already active" in capsys.readouterr().err
