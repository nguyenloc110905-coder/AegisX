import argparse
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisx",
        description="Run the local AegisX development stack.",
    )
    parser.add_argument("command", nargs="?", choices=("run", "doctor", "stop"), default="run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    return 0
