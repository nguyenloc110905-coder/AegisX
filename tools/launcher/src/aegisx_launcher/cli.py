import argparse
import sys
from collections.abc import Sequence

from aegisx_launcher.project import ProjectDiscoveryError, find_project_root, select_env_file
from aegisx_launcher.runtime import AegisXRuntime
from aegisx_launcher.state import LauncherState, LauncherStateError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisx",
        description="Run the local AegisX development stack.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "doctor", "stop", "dev-reset"),
        default="run",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="run API and agent logs without the terminal operator console",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm destructive development-only operations",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        root = find_project_root()
        env_file = select_env_file(root)
    except ProjectDiscoveryError as error:
        print(f"[failed] {error}", file=sys.stderr)
        return 2

    runtime = AegisXRuntime(root, env_file)
    if arguments.command == "doctor":
        return runtime.doctor()
    if arguments.command == "stop":
        return runtime.stop()
    try:
        with LauncherState.default():
            if arguments.command == "dev-reset":
                return runtime.dev_reset(confirmed=arguments.yes)
            return runtime.run(show_ui=not arguments.no_ui)
    except LauncherStateError as error:
        print(f"[failed] {error}", file=sys.stderr)
        return 3
