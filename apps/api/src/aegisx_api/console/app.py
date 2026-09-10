from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from aegisx_api.console.types import DashboardSnapshot


def _timestamp(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S") if value else "—"


def _endpoint(address: str | None, port: int | None) -> str:
    return f"{address}:{port}" if address is not None and port is not None else "—"


def _severity(value: str) -> Text:
    colors = {
        "informational": "dim",
        "normal": "dim",
        "low": "green",
        "medium": "yellow",
        "high": "bold orange1",
        "critical": "bold red",
    }
    return Text(value, style=colors.get(value.lower(), "white"))


class AegisXConsole(App[None]):
    TITLE = "AegisX — Operator Console"
    CSS = """
    Screen { background: #060d14; }
    Header, Footer { background: #0a1628; color: #4fc3f7; }
    #stats { height: 5; padding: 0 1; }
    .stat { width: 1fr; height: 100%; border: round #1e3a5f;
            background: #0d1b2a; content-align: center middle; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    DataTable { height: 1fr; border: round #1e3a5f; background: #060d14; }
    #log-panel { height: 3; padding: 0 1; color: #8fb8d8; }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_data", "Refresh"),
        Binding("1", "switch_tab('devices')", "Devices"),
        Binding("2", "switch_tab('events')", "Events"),
        Binding("3", "switch_tab('detections')", "Detections"),
        Binding("4", "switch_tab('candidates')", "Candidates"),
        Binding("5", "switch_tab('incidents')", "Incidents"),
    ]

    def __init__(self, loader: Callable[[], Awaitable[DashboardSnapshot]]) -> None:
        super().__init__()
        self._loader = loader

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal(id="stats"):
                yield Static("…", id="stat-devices", classes="stat")
                yield Static("…", id="stat-events", classes="stat")
                yield Static("…", id="stat-detections", classes="stat")
                yield Static("…", id="stat-candidates", classes="stat")
                yield Static("…", id="stat-incidents", classes="stat")
            with TabbedContent(id="tabs"):
                with TabPane("Devices [1]", id="devices"):
                    yield DataTable(id="tbl-devices", cursor_type="row", zebra_stripes=True)
                with TabPane("Events [2]", id="events"):
                    yield DataTable(id="tbl-events", cursor_type="row", zebra_stripes=True)
                with TabPane("Detections [3]", id="detections"):
                    yield DataTable(id="tbl-detections", cursor_type="row", zebra_stripes=True)
                with TabPane("Candidates [4]", id="candidates"):
                    yield DataTable(id="tbl-candidates", cursor_type="row", zebra_stripes=True)
                with TabPane("Incidents [5]", id="incidents"):
                    yield DataTable(id="tbl-incidents", cursor_type="row", zebra_stripes=True)
            yield Static("Starting…", id="log-panel")
        yield Footer()

    def on_mount(self) -> None:
        self._configure_tables()
        self.run_worker(self._refresh(), exclusive=True)

    def action_refresh_data(self) -> None:
        self.query_one("#log-panel", Static).update("Refreshing…")
        self.run_worker(self._refresh(), exclusive=True)

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    async def _refresh(self) -> None:
        try:
            snapshot = await self._loader()
        except Exception:
            self.query_one("#log-panel", Static).update(
                "Unable to load dashboard data. Check `aegisx doctor` or service logs."
            )
            return
        self._update_stats(snapshot)
        self._fill_tables(snapshot)
        self.query_one("#log-panel", Static).update(
            f"Connected · {snapshot.counts.events} events · "
            f"{snapshot.counts.detections} detections · press r to refresh"
        )

    def _configure_tables(self) -> None:
        self.query_one("#tbl-devices", DataTable).add_columns(
            "Name", "OS", "Version", "Kernel", "Arch", "Active", "Last seen"
        )
        self.query_one("#tbl-events", DataTable).add_columns(
            "Time", "Type", "PID", "Executable", "Local", "Remote", "Severity"
        )
        self.query_one("#tbl-detections", DataTable).add_columns(
            "Time", "Rule", "Severity", "Score", "Reason"
        )
        self.query_one("#tbl-candidates", DataTable).add_columns(
            "Time", "Strategy", "Confidence", "Score", "Reason"
        )
        self.query_one("#tbl-incidents", DataTable).add_columns(
            "Time", "Title", "Severity", "Risk", "Status", "Confidence", "Disposition"
        )

    def _update_stats(self, snapshot: DashboardSnapshot) -> None:
        values = {
            "stat-devices": (snapshot.counts.devices, "DEVICES"),
            "stat-events": (snapshot.counts.events, "EVENTS"),
            "stat-detections": (snapshot.counts.detections, "DETECTIONS"),
            "stat-candidates": (snapshot.counts.candidates, "CANDIDATES"),
            "stat-incidents": (snapshot.counts.open_incidents, "OPEN INCIDENTS"),
        }
        for widget_id, (value, label) in values.items():
            self.query_one(f"#{widget_id}", Static).update(
                f"[bold]{value}[/bold]\n[dim]{label}[/dim]"
            )

    def _fill_tables(self, snapshot: DashboardSnapshot) -> None:
        devices = self.query_one("#tbl-devices", DataTable)
        events = self.query_one("#tbl-events", DataTable)
        detections = self.query_one("#tbl-detections", DataTable)
        candidates = self.query_one("#tbl-candidates", DataTable)
        incidents = self.query_one("#tbl-incidents", DataTable)
        for table in (devices, events, detections, candidates, incidents):
            table.clear()
        for device_row in snapshot.devices:
            devices.add_row(
                device_row.name,
                device_row.os,
                device_row.os_version[:28],
                device_row.kernel[:22],
                device_row.architecture,
                "yes" if device_row.is_active else "no",
                _timestamp(device_row.last_seen_at),
                key=str(device_row.id),
            )
        for event_row in snapshot.events:
            events.add_row(
                _timestamp(event_row.timestamp),
                event_row.event_type,
                str(event_row.process_id or "—"),
                (event_row.executable or "—")[-36:],
                _endpoint(event_row.local_ip, event_row.local_port),
                _endpoint(event_row.remote_ip, event_row.remote_port),
                _severity(event_row.severity),
                key=str(event_row.id),
            )
        for detection_row in snapshot.detections:
            detections.add_row(
                _timestamp(detection_row.timestamp),
                detection_row.rule_id,
                _severity(detection_row.severity),
                str(detection_row.score),
                detection_row.reason[:80],
                key=str(detection_row.id),
            )
        for candidate_row in snapshot.candidates:
            candidates.add_row(
                _timestamp(candidate_row.timestamp),
                candidate_row.strategy_id,
                candidate_row.confidence,
                str(candidate_row.score),
                candidate_row.reason[:80],
                key=str(candidate_row.id),
            )
        for incident_row in snapshot.incidents:
            incidents.add_row(
                _timestamp(incident_row.timestamp),
                incident_row.title[:60],
                _severity(incident_row.severity),
                str(incident_row.risk_score),
                incident_row.status,
                incident_row.confidence,
                incident_row.disposition,
                key=str(incident_row.id),
            )
