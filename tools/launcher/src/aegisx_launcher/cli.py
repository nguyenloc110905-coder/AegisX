import argparse
import sys
from collections.abc import Sequence

from aegisx_launcher.project import ProjectDiscoveryError, find_project_root, select_env_file
from aegisx_launcher.runtime import AegisXRuntime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisx",
        description="Run the local AegisX development stack.",
    )
    parser.add_argument("command", nargs="?", choices=("run", "doctor", "stop"), default="run")
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
    return runtime.run()
