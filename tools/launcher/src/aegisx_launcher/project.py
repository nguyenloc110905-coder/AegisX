import os
from pathlib import Path


class ProjectDiscoveryError(RuntimeError):
    """Raised when the launcher cannot resolve a valid AegisX checkout."""


PACKAGE_LOCATION = Path(__file__).resolve()


def _is_project_root(path: Path) -> bool:
    return (path / "compose.yaml").is_file() and (path / "apps/api/pyproject.toml").is_file()


def _walk_up(start: Path) -> Path | None:
    candidate = start.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for path in (candidate, *candidate.parents):
        if _is_project_root(path):
            return path
    return None


def find_project_root(start: Path | None = None) -> Path:
    override = os.environ.get("AEGISX_PROJECT_ROOT")
    if override:
        explicit = Path(override).expanduser().resolve()
        if not _is_project_root(explicit):
            raise ProjectDiscoveryError(
                f"AEGISX_PROJECT_ROOT does not point to an AegisX checkout: {explicit}"
            )
        return explicit

    for location in (start or Path.cwd(), PACKAGE_LOCATION):
        discovered = _walk_up(location)
        if discovered is not None:
            return discovered
    raise ProjectDiscoveryError(
        "Could not locate AegisX. Run inside the checkout or set AEGISX_PROJECT_ROOT."
    )


def select_env_file(root: Path) -> Path:
    for name in (".env", ".env.example"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise ProjectDiscoveryError(f"No environment file found under AegisX root: {root}")
