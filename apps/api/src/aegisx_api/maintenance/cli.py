import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from aegisx_api.config import get_settings
from aegisx_api.db.session import create_engine, create_session_factory
from aegisx_api.maintenance.retention_service import RetentionPruneError, RetentionService
from aegisx_api.maintenance.types import DataStatus, PruneReport, PruneResult


class RetentionOperations(Protocol):
    async def data_status(self) -> DataStatus: ...

    async def dry_run(self, evaluation_time: datetime) -> PruneReport: ...

    async def prune(self, evaluation_time: datetime) -> PruneResult: ...


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegisx-maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("data-status")
    prune = subparsers.add_parser("prune")
    mode = prune.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    prune.add_argument("--yes", action="store_true")
    return parser


def _render_status(status: DataStatus) -> None:
    print(
        f"policy_version={status.policy_version} database_size_bytes={status.database_size_bytes}"
    )
    print(
        f"events={status.event_count} detections={status.detection_count} "
        f"candidates={status.candidate_count} incidents={status.incident_count} "
        f"protected_events={status.protected_event_count}"
    )
    for row in status.event_types:
        print(
            f"event_type={row.event_type} count={row.count} "
            f"oldest={row.oldest_ingested_at.isoformat() if row.oldest_ingested_at else '-'} "
            f"newest={row.newest_ingested_at.isoformat() if row.newest_ingested_at else '-'}"
        )


def _render_report(report: PruneReport) -> None:
    print(
        f"mode=dry-run policy_version={report.policy_version} "
        f"evaluation_time={report.evaluation_time.isoformat()}"
    )
    for row in report.rules:
        print(
            f"event_type={row.event_type} cutoff={row.cutoff.isoformat()} "
            f"expired_events={row.expired_events} protected_events={row.protected_events} "
            f"deletable_events={row.deletable_events} "
            f"deletable_detections={row.deletable_detections}"
        )
    print(
        f"total_expired_events={report.expired_events} "
        f"total_protected_events={report.protected_events} "
        f"total_deletable_events={report.deletable_events} "
        f"total_deletable_detections={report.deletable_detections}"
    )


def _render_result(result: PruneResult) -> None:
    print(
        f"mode=apply policy_version={result.policy_version} "
        f"completed={str(result.completed).lower()} "
        f"deleted_events={result.deleted_events} "
        f"deleted_detections={result.deleted_detections}"
    )


async def run_command(argv: Sequence[str], service: RetentionOperations) -> int:
    arguments = _parser().parse_args(argv)
    evaluation_time = datetime.now(UTC)
    if arguments.command == "data-status":
        _render_status(await service.data_status())
        return 0
    if arguments.apply:
        if not arguments.yes:
            print("[refused] prune --apply requires --yes", file=sys.stderr)
            return 2
        _render_result(await service.prune(evaluation_time))
        return 0
    _render_report(await service.dry_run(evaluation_time))
    return 0


async def _main(argv: Sequence[str]) -> int:
    engine = create_engine(get_settings())
    try:
        service = RetentionService(create_session_factory(engine))
        return await run_command(argv, service)
    except RetentionPruneError as error:
        print(
            f"[failed] prune category={error.failure_category} "
            f"committed_events={error.deleted_events} "
            f"committed_detections={error.deleted_detections}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(f"[failed] maintenance category={type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(tuple(sys.argv[1:] if argv is None else argv)))
