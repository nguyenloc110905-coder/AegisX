import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class AgentCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    device_id: str
    token: str


def load_credentials(path: Path) -> AgentCredentials | None:
    try:
        return AgentCredentials.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def save_credentials(path: Path, credentials: AgentCredentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(credentials.model_dump(), stream)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
