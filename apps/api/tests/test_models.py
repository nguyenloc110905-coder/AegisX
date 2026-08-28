from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegisx_api.db.base import Base
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_device_and_event_are_persisted_with_relationship(session) -> None:
    device = Device(
        external_id="fedora-laptop-01",
        name="Fedora Laptop",
        os="Linux",
        os_version="Fedora 42",
        kernel="6.15.9",
        architecture="x86_64",
        token_digest="a" * 64,
    )
    event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="system.status",
        source="system_collector",
        severity_hint="normal",
        data={"hostname": "fedora-laptop"},
        metadata_={},
    )
    session.add(event)
    await session.commit()

    persisted = await session.scalar(select(Event).where(Event.id == event.id))

    assert persisted is not None
    assert persisted.device_id == device.id
    assert persisted.event_type == "system.status"


@pytest.mark.asyncio
async def test_device_external_id_is_unique(session) -> None:
    common = {
        "external_id": "same-device",
        "name": "Laptop",
        "os": "Linux",
        "os_version": "Fedora 42",
        "kernel": "6.15.9",
        "architecture": "x86_64",
    }
    session.add(Device(**common, token_digest="a" * 64))
    await session.commit()
    session.add(Device(**common, token_digest="b" * 64))

    with pytest.raises(IntegrityError):
        await session.commit()
