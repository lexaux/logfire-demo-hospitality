"""Smoke tests for the support assistant API."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
