"""Smoke tests for the support assistant API."""

import pytest
from httpx import ASGITransport, AsyncClient

import src.main as main_module
from src.main import app
from src.pms_status_app import app as pms_status_app

TEST_BASE_URL = "http://test"
PMS_STATUS_BASE_URL = "http://pms-status"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    pms_transport = ASGITransport(app=pms_status_app)
    # Let the agent's check_pms_status tool route to the PMS status app via ASGI
    main_module.agent_pms_status_transport = pms_transport
    async with app.router.lifespan_context(app), \
            pms_status_app.router.lifespan_context(pms_status_app):
        async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as ac:
            yield ac
    main_module.agent_pms_status_transport = None


@pytest.fixture
async def pms_client():
    transport = ASGITransport(app=pms_status_app)
    async with pms_status_app.router.lifespan_context(pms_status_app):
        async with AsyncClient(transport=transport, base_url=PMS_STATUS_BASE_URL) as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_config(client):
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "mews" in data["pms_systems"]


@pytest.mark.asyncio
async def test_list_tickets_empty(client):
    resp = await client.get("/api/tickets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_resolved_tickets_seeded(client):
    resp = await client.get("/api/tickets/resolved")
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) == 26


@pytest.mark.asyncio
async def test_pms_status_operational(pms_client):
    resp = await pms_client.get("/api/pms-status/mews")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system"] == "mews"
    assert data["status"] == "operational"
    assert data["incident"] is None


@pytest.mark.asyncio
async def test_pms_status_degraded(pms_client):
    resp = await pms_client.get("/api/pms-status/hostaway")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system"] == "hostaway"
    assert data["status"] == "degraded"
    assert "Webhook delivery delays" in data["incident"]


@pytest.mark.asyncio
async def test_pms_status_unknown_system(pms_client):
    resp = await pms_client.get("/api/pms-status/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_ticket(client):
    resp = await client.post(
        "/api/tickets",
        json={
            "subject": "Test webhook issue",
            "description": (
                "Webhook events are being duplicated when a reservation is updated in Mews"
            ),
            "pms_system": "mews",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] is not None
    valid_categories = ["billing", "sync_issue", "config", "not_supported", "bug", "unknown"]
    assert data["ai_category"] in valid_categories
    assert data["ai_priority"] in ["P1", "P2", "P3"]
    assert data["ai_confidence"] in ["high", "medium", "low"]
    assert len(data["ai_resolution_suggestion"]) > 10


@pytest.mark.asyncio
async def test_list_tickets_after_create(client):
    await client.post(
        "/api/tickets",
        json={
            "subject": "Rate sync not working",
            "description": (
                "Cloudbeds rates are not syncing to our guest platform after currency change"
            ),
            "pms_system": "cloudbeds",
        },
    )
    resp = await client.get("/api/tickets")
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) >= 1
