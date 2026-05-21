from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import logfire
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from logfire import VariablesOptions

from src.agent import TicketDeps, format_ticket_prompt, support_agent
from src.config import settings
from src.database import async_session, init_db
from src.knowledge import build_doc_chunks, load_integration_docs
from src.models import Ticket
from src.schemas import EscalationEntry, TicketCreate, TicketResponse
from src.seed import seed_tickets

# App-level state populated at startup
doc_chunks: list[dict] = []
escalation_configs: list[EscalationEntry] = []
# Set by tests/evals to route the agent's PMS-status HTTP calls through ASGI
agent_pms_status_transport: httpx.AsyncBaseTransport | None = None

logfire.configure(
    environment="local",
    service_name="tkt_agent",
    distributed_tracing=True,
    variables=VariablesOptions(),
    # advanced=logfire.AdvancedOptions(base_url='http://localhost:8080')
)
logfire.instrument_httpx()
logfire.instrument_sqlite3()
logfire.instrument_sqlalchemy()
logfire.instrument_pydantic_ai()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global doc_chunks, escalation_configs

    # Init database and seed
    await init_db()
    async with async_session() as session:
        await seed_tickets(session)

    # Load knowledge base
    docs = load_integration_docs()
    doc_chunks = build_doc_chunks(docs)

    # Load escalation config
    esc_path = Path("data/escalation_config.yaml")
    with open(esc_path) as f:
        raw = yaml.safe_load(f)
    escalation_configs = [EscalationEntry.model_validate(e) for e in raw]

    yield


app = FastAPI(title="Hospitality Integration Support", lifespan=lifespan)

logfire.instrument_fastapi(app=app)


@app.post("/api/tickets", response_model=TicketResponse)
async def create_ticket(ticket_in: TicketCreate):
    async with async_session() as session:
        # Insert new ticket
        ticket = Ticket(
            subject=ticket_in.subject,
            description=ticket_in.description,
            pms_system=ticket_in.pms_system,
            status="open",
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        logfire.info(f" MANUAL: Processing ticket {ticket.id}...")

        # Run AI agent
        deps = TicketDeps(
            db_session=session,
            doc_chunks=doc_chunks,
            escalation_configs=escalation_configs,
            pms_system=ticket_in.pms_system,
            app_base_url=settings.app_base_url,
            pms_status_base_url=settings.pms_status_base_url,
            pms_status_transport=agent_pms_status_transport,
        )

        # Structured wrapper span — input + output match the curated dataset
        # schema (TicketInput → TicketResolution). The Logfire "Add to dataset"
        # flow reads attributes from this span, so curation pre-populates both
        # input and expected_output without manual editing.
        with logfire.span(
            "support_ticket_resolution",
            ticket=ticket_in.model_dump(mode="json"),
        ) as ticket_span:
            try:
                result = await support_agent.run(
                    format_ticket_prompt(ticket.id, ticket_in),
                    deps=deps,
                )
                resolution = result.output
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Agent error: {e}") from e

            ticket_span.set_attribute("resolution", resolution.model_dump(mode="json"))

        # Update ticket with AI results
        ticket.ai_category = resolution.category
        ticket.ai_priority = resolution.priority
        ticket.ai_confidence = resolution.confidence
        ticket.ai_resolution_suggestion = resolution.resolution_suggestion
        ticket.source_docs_referenced = resolution.source_docs_referenced
        ticket.similar_ticket_ids = resolution.similar_ticket_ids
        ticket.escalation_recommended = resolution.escalation_recommended
        ticket.status = "escalated" if resolution.escalation_recommended else "resolved"

        await session.commit()
        await session.refresh(ticket)

        return TicketResponse.model_validate(ticket)


@app.get("/api/tickets", response_model=list[TicketResponse])
async def list_tickets():
    from sqlalchemy import desc, select

    async with async_session() as session:
        result = await session.execute(
            select(Ticket)
            .where(Ticket.resolution_notes.is_(None))
            .order_by(desc(Ticket.created_at))
            .limit(10)
        )
        return [TicketResponse.model_validate(t) for t in result.scalars().all()]


@app.get("/api/tickets/resolved", response_model=list[TicketResponse])
async def list_resolved_tickets():
    from sqlalchemy import desc, select

    async with async_session() as session:
        result = await session.execute(
            select(Ticket)
            .where(Ticket.resolution_notes.is_not(None))
            .order_by(desc(Ticket.created_at))
            .limit(30)
        )
        return [TicketResponse.model_validate(t) for t in result.scalars().all()]


@app.get("/api/tickets/by-ids", response_model=list[TicketResponse])
async def get_tickets_by_ids(ids: str):
    """Fetch tickets by comma-separated IDs."""
    from sqlalchemy import select

    try:
        id_list = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError:
        return []

    async with async_session() as session:
        result = await session.execute(select(Ticket).where(Ticket.id.in_(id_list)))
        return [TicketResponse.model_validate(t) for t in result.scalars().all()]


@app.get("/api/config")
async def get_config():
    return {
        "pms_systems": ["mews", "cloudbeds", "hostaway"],
    }


# Serve frontend
frontend_dir = Path("frontend")


@app.get("/")
async def serve_index():
    return FileResponse(frontend_dir / "index.html")


if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")
