from fastapi import APIRouter

from aegisx_api.api.devices import router as devices_router
from aegisx_api.api.health import router as health_router
from aegisx_api.api.telemetry import router as telemetry_router

router = APIRouter()
router.include_router(health_router)
router.include_router(devices_router, prefix="/api/v1")
router.include_router(telemetry_router, prefix="/api/v1")
