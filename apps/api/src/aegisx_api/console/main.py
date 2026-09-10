import asyncio
from datetime import timedelta

from aegisx_api.config import Settings
from aegisx_api.console.app import AegisXConsole
from aegisx_api.console.repository import ConsoleRepository


async def _run() -> None:
    settings = Settings()
    repository = ConsoleRepository.from_url(
        settings.database_url,
        stale_after=timedelta(seconds=settings.device_stale_after_seconds),
    )
    try:
        await AegisXConsole(repository.load).run_async()
    finally:
        await repository.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
