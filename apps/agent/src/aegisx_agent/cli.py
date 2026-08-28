import argparse
import asyncio
import json

from aegisx_agent.config import AgentSettings
from aegisx_agent.runner import collect_once


def main() -> None:
    parser = argparse.ArgumentParser(prog="aegisx-agent")
    parser.add_argument("command", choices=["collect-once"])
    arguments = parser.parse_args()
    if arguments.command == "collect-once":
        result = asyncio.run(collect_once(AgentSettings()))
        print(json.dumps(result.model_dump()))
