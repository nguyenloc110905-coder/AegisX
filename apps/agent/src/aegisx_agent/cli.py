import argparse
import asyncio
import json
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from aegisx_agent.config import AgentSettings
from aegisx_agent.local_store import LocalStoreError, LocalTelemetryStore
from aegisx_agent.local_types import (
    LocalDataStatus,
    LocalPruneReport,
    LocalPruneResult,
    LocalVerifyResult,
)
from aegisx_agent.logging import configure_logging
from aegisx_agent.runner import collect_once
from aegisx_agent.service import run_periodically

StoreFactory = Callable[[Path, int, int], LocalTelemetryStore]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegisx-agent")
    parser.add_argument(
        "command",
        choices=[
            "collect-once",
            "run",
            "local-data-status",
            "local-verify",
            "local-prune",
        ],
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser


def _render_status(status: LocalDataStatus) -> None:
    print(
        f"policy_version={status.policy_version} schema_version={status.schema_version} "
        f"logical_payload_bytes={status.logical_payload_bytes} "
        f"database_file_bytes={status.database_file_bytes} event_count={status.event_count} "
        f"pending={status.pending_count} acknowledged={status.acknowledged_count} "
        f"quarantined={status.quarantined_count} coverage_gaps={status.coverage_gap_count}"
    )
    for item in status.event_types:
        print(
            f"event_type={item.event_type} count={item.count} payload_bytes={item.payload_bytes} "
            f"oldest={item.oldest_recorded_at.isoformat()} "
            f"newest={item.newest_recorded_at.isoformat()}"
        )


def _render_verify(result: LocalVerifyResult) -> None:
    first_bad = "none" if result.first_bad_sequence is None else result.first_bad_sequence
    failure = result.failure_category or "none"
    print(
        f"valid={str(result.valid).lower()} checked_events={result.checked_events} "
        f"first_bad_sequence={first_bad} failure_category={failure}"
    )


def _render_prune_report(report: LocalPruneReport) -> None:
    print(
        f"mode=dry-run policy_version={report.policy_version} "
        f"evaluation_time={report.evaluation_time.isoformat()} "
        f"eligible_events={report.eligible_events} "
        f"eligible_payload_bytes={report.eligible_payload_bytes}"
    )
    for rule in report.rules:
        print(
            f"priority={rule.priority.value} cutoff={rule.cutoff.isoformat()} "
            f"eligible_events={rule.eligible_events} "
            f"eligible_payload_bytes={rule.eligible_payload_bytes}"
        )


def _render_prune_result(result: LocalPruneResult) -> None:
    print(
        f"mode=apply policy_version={result.policy_version} "
        f"evaluation_time={result.evaluation_time.isoformat()} "
        f"completed={str(result.completed).lower()} deleted_events={result.deleted_events} "
        f"deleted_payload_bytes={result.deleted_payload_bytes}"
    )


def run_command(
    argv: Sequence[str],
    *,
    settings: AgentSettings | None = None,
    store_factory: StoreFactory = LocalTelemetryStore,
) -> int:
    arguments = _parser().parse_args(argv)
    resolved_settings = settings or AgentSettings()
    if arguments.command == "collect-once":
        collection_result = asyncio.run(collect_once(resolved_settings))
        print(json.dumps(collection_result.model_dump()))
        return 0
    if arguments.command == "run":
        try:
            asyncio.run(run_periodically(resolved_settings))
        except KeyboardInterrupt:
            return 130
        return 0
    if arguments.command == "local-prune":
        if not arguments.dry_run and not arguments.apply:
            print("[refused] choose exactly one mode: --dry-run or --apply", file=sys.stderr)
            return 2
        if arguments.apply and not arguments.yes:
            print("[refused] local-prune --apply requires --yes", file=sys.stderr)
            return 2

    try:
        store = store_factory(
            resolved_settings.state_directory / "outbox.sqlite3",
            resolved_settings.max_outbox_events,
            resolved_settings.local_telemetry_max_bytes,
        )
    except (LocalStoreError, OSError, ValueError, sqlite3.Error) as error:
        print(f"[failed] local_store category={type(error).__name__}", file=sys.stderr)
        return 1
    try:
        if arguments.command == "local-data-status":
            _render_status(store.data_status())
            return 0
        if arguments.command == "local-verify":
            verification_result = store.verify()
            _render_verify(verification_result)
            return 0 if verification_result.valid else 1
        evaluation_time = datetime.now(UTC)
        if arguments.dry_run:
            _render_prune_report(store.dry_run(evaluation_time))
        else:
            _render_prune_result(store.prune(evaluation_time))
        return 0
    except (LocalStoreError, OSError, ValueError, sqlite3.Error) as error:
        print(f"[failed] local_store category={type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        store.close()


def main() -> None:
    configure_logging()
    raise SystemExit(run_command(sys.argv[1:]))
