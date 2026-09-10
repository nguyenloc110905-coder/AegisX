import fcntl
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import TypedDict
from uuid import uuid4


class LauncherStateError(RuntimeError):
    """Raised when launcher ownership cannot be established safely."""


class LauncherAlreadyRunningError(LauncherStateError):
    """Raised when another live launcher owns the state."""


class StatePayload(TypedDict):
    pid: int
    instance_id: str


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LauncherState:
    def __init__(
        self,
        path: Path,
        *,
        pid: int | None = None,
        instance_id: str | None = None,
        pid_is_alive: Callable[[int], bool] = _pid_is_alive,
    ) -> None:
        self.path = path
        self.pid = pid if pid is not None else os.getpid()
        self.instance_id = instance_id or str(uuid4())
        self._pid_is_alive = pid_is_alive
        self._lock_fd: int | None = None

    @classmethod
    def default(cls) -> "LauncherState":
        configured = os.environ.get("AEGISX_AGENT_STATE_DIR")
        if configured:
            directory = Path(configured).expanduser()
        else:
            state_home = Path(
                os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
            ).expanduser()
            directory = state_home / "aegisx"
        return cls(directory / "launcher.json")

    def acquire(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(lock_fd)
            raise LauncherAlreadyRunningError(
                "Another AegisX launcher is already running"
            ) from error
        self._lock_fd = lock_fd

        try:
            existing = self._read_existing()
            if existing is not None:
                existing_pid = existing["pid"]
                if self._pid_is_alive(existing_pid):
                    raise LauncherAlreadyRunningError(
                        f"Another AegisX launcher is already running as PID {existing_pid}"
                    )
            self._write_atomic()
        except Exception:
            self._unlock()
            raise

    def _read_existing(self) -> StatePayload | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            pid = raw["pid"]
            instance_id = raw["instance_id"]
            if not isinstance(pid, int) or not isinstance(instance_id, str) or not instance_id:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise LauncherStateError(
                f"Existing launcher state is malformed: {self.path}"
            ) from error
        return StatePayload(pid=pid, instance_id=instance_id)

    def _write_atomic(self) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".launcher-", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            payload = json.dumps(
                {"instance_id": self.instance_id, "pid": self.pid},
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def release(self) -> None:
        try:
            existing = self._read_existing()
            if existing is not None and existing["instance_id"] == self.instance_id:
                self.path.unlink(missing_ok=True)
        except LauncherStateError:
            pass
        finally:
            self._unlock()

    def _unlock(self) -> None:
        if self._lock_fd is None:
            return
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        os.close(self._lock_fd)
        self._lock_fd = None

    def __enter__(self) -> "LauncherState":
        self.acquire()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
