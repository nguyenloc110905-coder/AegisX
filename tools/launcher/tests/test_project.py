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
