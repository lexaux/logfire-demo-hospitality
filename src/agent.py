from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai import Agent, ModelSettings, RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.knowledge import search_chunks
from src.models import Ticket
from src.schemas import EscalationEntry, PmsSystem, TicketResolution

SYSTEM_PROMPT = f"""\
You are a hospitality integration support assistant. You help support teams diagnose \
and resolve issues between Property Management Systems (PMS) and a Guest Experience Platform.

Supported PMS systems: {", ".join(m.value for m in PmsSystem)}.

When given a support ticket, you must:
1. Search the integration documentation for relevant information
2. Look for similar previously resolved tickets
3. If the issue is high priority (P1) or you have low confidence, get escalation context

Pick the most specific category. Follow the field descriptions in the output schema closely.

Set escalation_recommended to true if priority is P1, confidence is low, or the system is degraded.

Be precise. Cite specific doc sections and bug IDs when available. \
If the issue isn't covered in docs, say so and recommend escalation.\
"""


@dataclass
class TicketDeps:
    db_session: AsyncSession
    doc_chunks: list[dict]
    escalation_configs: list[EscalationEntry]
    pms_system: str


support_agent = Agent(
    settings.model_name,
    deps_type=TicketDeps,
    output_type=TicketResolution,
    system_prompt=SYSTEM_PROMPT,
    model_settings=ModelSettings(temperature=0),
    defer_model_check=True,
)


@support_agent.tool
async def search_integration_docs(
    ctx: RunContext[TicketDeps],
    query: str,
    systems: list[str],
) -> list[dict]:
    """Search integration documentation for relevant information.

    Args:
        query: Natural language search query about the integration issue.
        systems: List of PMS system names to search (e.g. ["mews", "cloudbeds"]).
    """
    results = search_chunks(ctx.deps.doc_chunks, query, systems)
    return [
        {
            "system": r["system"],
            "category": r["category"],
            "section": r["section_title"],
            "content": r["content"],
            "relevance_score": r["relevance_score"],
        }
        for r in results
    ]


@support_agent.tool
async def find_similar_tickets(
    ctx: RunContext[TicketDeps],
    description: str,
    system_filter: str | None = None,
) -> list[dict]:
    """Find similar previously resolved tickets.

    Args:
        description: The ticket description to find similar tickets for.
        system_filter: Optional PMS system name to filter by.
    """
    query = select(Ticket).where(Ticket.status == "resolved")
    if system_filter:
        query = query.where(Ticket.pms_system == system_filter)

    result = await ctx.deps.db_session.execute(query)
    resolved_tickets = result.scalars().all()

    # Simple keyword overlap scoring
    desc_terms = set(description.lower().split())
    scored = []
    for ticket in resolved_tickets:
        ticket_terms = set(f"{ticket.subject} {ticket.description}".lower().split())
        overlap = len(desc_terms & ticket_terms)
        if overlap > 2:  # Minimum relevance threshold
            score = round(overlap / max(len(desc_terms), 1), 2)
            scored.append(
                {
                    "ticket_id": ticket.id,
                    "subject": ticket.subject,
                    "resolution_notes": ticket.resolution_notes or "",
                    "ai_resolution_suggestion": ticket.ai_resolution_suggestion or "",
                    "similarity_score": score,
                }
            )

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored[:3]


@support_agent.tool
async def get_escalation_context(
    ctx: RunContext[TicketDeps],
    priority: str,
    pms_system: str,
) -> dict:
    """Get escalation context for a ticket. Call this when priority is P1 or confidence is low.

    Args:
        priority: The ticket priority (P1, P2, P3).
        pms_system: The PMS system name.
    """
    for config in ctx.deps.escalation_configs:
        if config.pms_system == pms_system:
            return {
                "sla_hours": config.sla_hours,
                "owner_team": config.owner_team,
                "currently_degraded": config.currently_degraded,
                "escalation_notes": config.escalation_notes,
            }
    return {
        "sla_hours": 24,
        "owner_team": "general-support",
        "currently_degraded": False,
        "escalation_notes": "No specific escalation config found for this system.",
    }
