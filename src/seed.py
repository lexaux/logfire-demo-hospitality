from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Ticket
from src.schemas import SeededTicket


async def seed_tickets(session: AsyncSession, data_path: str = "data/seeded_tickets.yaml"):
    """Load seeded tickets from YAML and insert into DB if not already present."""
    result = await session.execute(select(Ticket).where(Ticket.status == "resolved").limit(1))
    if result.scalar_one_or_none() is not None:
        return  # Already seeded

    path = Path(data_path)
    if not path.exists():
        return

    with open(path) as f:
        raw_tickets = yaml.safe_load(f)

    for raw in raw_tickets:
        validated = SeededTicket.model_validate(raw)
        ticket = Ticket(
            subject=validated.subject,
            description=validated.description,
            integration=validated.integration,
            status=validated.status,
            ai_category=validated.ai_category,
            ai_priority=validated.ai_priority,
            ai_confidence=validated.ai_confidence,
            ai_resolution_suggestion=validated.ai_resolution_suggestion,
            resolution_notes=validated.resolution_notes,
            source_docs_referenced=validated.source_docs_referenced,
            similar_ticket_ids=validated.similar_ticket_ids,
            escalation_recommended=validated.escalation_recommended,
        )
        session.add(ticket)

    await session.commit()
