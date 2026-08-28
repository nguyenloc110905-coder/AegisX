import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DeviceIdentity:
    external_id: str


def load_or_create_identity(path: Path) -> DeviceIdentity:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        external_id = str(UUID(raw["external_id"]))
        return DeviceIdentity(external_id=external_id)
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = DeviceIdentity(external_id=str(uuid4()))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"external_id": identity.external_id}, stream)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return identity
