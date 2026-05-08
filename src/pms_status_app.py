from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import logfire
import yaml
from fastapi import FastAPI, HTTPException

from src.schemas import PmsStatus

pms_statuses: dict[str, PmsStatus] = {}

logfire.configure(
    environment="local", service_name="pms-status-service", distributed_tracing=True,
    # advanced=logfire.AdvancedOptions(base_url='http://localhost:8080')
)
logfire.instrument_httpx()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pms_statuses
    status_path = Path("data/pms_status.yaml")
    with open(status_path) as f:
        status_raw = yaml.safe_load(f)
    for entry in status_raw:
        s = PmsStatus.model_validate(entry)
        pms_statuses[s.system] = s
    yield


app = FastAPI(title="PMS Status Service", lifespan=lifespan)
logfire.instrument_fastapi(app=app)


@app.get("/api/pms-status/{system}")
async def get_pms_status(system: str):
    """Mock PMS vendor status endpoint."""
    status = pms_statuses.get(system)
    if not status:
        raise HTTPException(status_code=404, detail=f"Unknown system: {system}")
    return status.model_dump()
