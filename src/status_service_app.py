from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import logfire
import yaml
from fastapi import FastAPI, HTTPException

from src.schemas import ServiceStatus

service_statuses: dict[str, ServiceStatus] = {}

logfire.configure(
    environment="local",
    service_name="service-status",
    distributed_tracing=True,
    # advanced=logfire.AdvancedOptions(base_url='http://localhost:8080')
)
logfire.instrument_httpx()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service_statuses
    status_path = Path("data/service_status.yaml")
    with open(status_path) as f:
        status_raw = yaml.safe_load(f)
    for entry in status_raw:
        s = ServiceStatus.model_validate(entry)
        service_statuses[s.system] = s
    yield


app = FastAPI(title="Upstream Service Status", lifespan=lifespan)
logfire.instrument_fastapi(app=app)


@app.get("/api/service-status/{system}")
async def get_service_status(system: str):
    """Mock upstream-service status endpoint."""
    status = service_statuses.get(system)
    if not status:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {system}")
    return status.model_dump()
