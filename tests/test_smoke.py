"""Smoke tests for the support assistant API."""

import pytest
from httpx import ASGITransport, AsyncClient

import src.main as main_module
from src.main import app
from src.status_service_app import app as status_service_app

TEST_BASE_URL = "http://test"
STATUS_BASE_URL = "http://service-status"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    status_transport = ASGITransport(app=status_service_app)
    # Let the agent's check_service_status tool route via ASGI
    main_module.agent_status_service_transport = status_transport
    async with (
        app.router.lifespan_context(app),
        status_service_app.router.lifespan_context(status_service_app),
    ):
        async with AsyncClient(transport=transport, base_url=TEST_BASE_URL) as ac:
            yield ac
    main_module.agent_status_service_transport = None


@pytest.fixture
async def status_client():
    transport = ASGITransport(app=status_service_app)
    async with status_service_app.router.lifespan_context(status_service_app):
        async with AsyncClient(transport=transport, base_url=STATUS_BASE_URL) as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_config(client):
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "stripe" in data["integrations"]


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
    assert len(tickets) >= 1


@pytest.mark.asyncio
async def test_service_status_operational(status_client):
    resp = await status_client.get("/api/service-status/stripe")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system"] == "stripe"
    assert data["status"] == "operational"
    assert data["incident"] is None


@pytest.mark.asyncio
async def test_service_status_degraded(status_client):
    resp = await status_client.get("/api/service-status/sendgrid")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system"] == "sendgrid"
    assert data["status"] == "degraded"
    assert "delivery" in data["incident"].lower()


@pytest.mark.asyncio
async def test_service_status_unknown(status_client):
    resp = await status_client.get("/api/service-status/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_ticket(client):
    resp = await client.post(
        "/api/tickets",
        json={
            "subject": "Test webhook issue",
            "description": (
                "Stripe webhook events are being delivered twice for charge.succeeded"
            ),
            "integration": "stripe",
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
            "subject": "Twilio SMS delivery delay",
            "description": (
                "SMS messages sent via Twilio Programmable Messaging are arriving "
                "10+ minutes late for European numbers"
            ),
            "integration": "twilio",
        },
    )
    resp = await client.get("/api/tickets")
    assert resp.status_code == 200
    tickets = resp.json()
    assert len(tickets) >= 1
