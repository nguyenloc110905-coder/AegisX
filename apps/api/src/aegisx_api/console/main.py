import asyncio

from aegisx_api.config import Settings
from aegisx_api.console.app import AegisXConsole
from aegisx_api.console.repository import ConsoleRepository


async def _run() -> None:
    repository = ConsoleRepository.from_url(Settings().database_url)
    try:
        await AegisXConsole(repository.load).run_async()
    finally:
        await repository.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
