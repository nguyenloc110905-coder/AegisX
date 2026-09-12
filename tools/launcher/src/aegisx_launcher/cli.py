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
        choices=(
            "run",
            "doctor",
            "stop",
            "dev-reset",
            "data-status",
            "prune",
            "local-data-status",
            "local-verify",
            "local-prune",
        ),
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
    prune_mode = parser.add_mutually_exclusive_group()
    prune_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="show eligible retention data without deleting it",
    )
    prune_mode.add_argument(
        "--apply",
        action="store_true",
        help="apply retention deletion (also requires --yes)",
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
    if arguments.command == "data-status":
        return runtime.data_status()
    if arguments.command == "local-data-status":
        return runtime.local_data_status()
    if arguments.command == "local-verify":
        return runtime.local_verify()
    if arguments.command == "prune" and not arguments.apply:
        if not arguments.dry_run:
            print("[refused] choose exactly one mode: --dry-run or --apply", file=sys.stderr)
            return 2
        return runtime.prune(apply=False, confirmed=False)
    if arguments.command == "local-prune" and not arguments.apply:
        if not arguments.dry_run:
            print("[refused] choose exactly one mode: --dry-run or --apply", file=sys.stderr)
            return 2
        return runtime.local_prune(apply=False, confirmed=False)
    if arguments.command == "local-prune" and not arguments.yes:
        print("[refused] local-prune --apply requires --yes", file=sys.stderr)
        return 2
    try:
        with LauncherState.default():
            if arguments.command == "dev-reset":
                return runtime.dev_reset(confirmed=arguments.yes)
            if arguments.command == "prune":
                return runtime.prune(apply=True, confirmed=arguments.yes)
            if arguments.command == "local-prune":
                return runtime.local_prune(apply=True, confirmed=arguments.yes)
            return runtime.run(show_ui=not arguments.no_ui)
    except LauncherStateError as error:
        print(f"[failed] {error}", file=sys.stderr)
        return 3
