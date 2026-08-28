import argparse
import asyncio
import json

from aegisx_agent.config import AgentSettings
from aegisx_agent.logging import configure_logging
from aegisx_agent.runner import collect_once
from aegisx_agent.service import run_periodically


def main() -> None:
    parser = argparse.ArgumentParser(prog="aegisx-agent")
    parser.add_argument("command", choices=["collect-once", "run"])
    arguments = parser.parse_args()
    configure_logging()
    if arguments.command == "collect-once":
        result = asyncio.run(collect_once(AgentSettings()))
        print(json.dumps(result.model_dump()))
    else:
        try:
            asyncio.run(run_periodically(AgentSettings()))
        except KeyboardInterrupt:
            pass
