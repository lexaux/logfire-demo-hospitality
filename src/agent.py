from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import httpx
import logfire
from pydantic_ai import Agent, ModelSettings, RunContext
from pydantic_evals.online import OnlineEvaluator, SamplingContext
from pydantic_evals.online_capability import OnlineEvaluation
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evals.evaluators import (
    ReferenceKind,
    escalation_judge,
    evidence_judge,
    resolution_quality_score,
)
from src.knowledge import search_chunks
from src.llm import llm_model
from src.models import Ticket
from src.schemas import EscalationEntry, Integration, TicketInput, TicketResolution

INTEGRATIONS_LIST = ", ".join(m.value for m in Integration)


def format_ticket_prompt(ticket_id: int | None, ticket: TicketInput) -> str:
    """Render a structured ticket as the LLM-facing user prompt.

    Single source of truth — used by the FastAPI handler and the eval runner.
    """
    header = f"Ticket #{ticket_id}\n" if ticket_id is not None else ""
    return (
        f"{header}"
        f"Integration: {ticket.integration}\n"
        f"Subject: {ticket.subject}\n"
        f"Description: {ticket.description}"
    )


# Fallback used if Logfire is unreachable; production prompt is managed in Logfire
# under variable `prompt__new_prompt` (display name: support_agent_prompt).
SYSTEM_PROMPT_FALLBACK = """\
You are an integration support assistant. You help support teams diagnose \
and resolve issues between our platform and third-party services (payments, messaging, email).

Supported integrations: {{integrations}}.

When given a support ticket, you must:
1. Search the integration documentation for relevant information
2. Check the upstream service's status to see if the provider has issues that may explain the problem
3. Look for similar previously resolved tickets
4. If the issue is high priority (P1) or you have low confidence, get escalation context

Pick the most specific category. Follow the field descriptions in the output schema closely.

Set escalation_recommended to true if priority is P1, confidence is low, or the upstream service is degraded.

Be precise. Cite specific doc sections and bug IDs when available. If the issue isn't covered in docs, say so and recommend escalation.
"""


@cache
def _prompt_var():
    var = logfire.var(name="prompt__new_prompt", default=SYSTEM_PROMPT_FALLBACK)
    var.refresh_sync(force=True)
    return var


def _render_template(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


@dataclass
class TicketDeps:
    db_session: AsyncSession
    doc_chunks: list[dict]
    escalation_configs: list[EscalationEntry]
    integration: str
    app_base_url: str = "http://localhost:8000"
    status_service_base_url: str = "http://localhost:8001"
    http_transport: httpx.AsyncBaseTransport | None = None
    status_service_transport: httpx.AsyncBaseTransport | None = None


def _evidence_judge_predicate(ctx: SamplingContext) -> bool:
    """Run the evidence judge only on Stripe tickets.

    `ctx.inputs` is the user-prompt string that `format_ticket_prompt` produced
    (`"Integration: stripe\\nSubject: ..."`). Returning True dispatches the
    evaluator; False skips it entirely (no LLM call, no result span).
    """
    decision = "stripe" in str(ctx.inputs).lower()
    logfire.debug(
        "evidence_judge sample decision",
        decision=decision,
        evaluator=type(ctx.evaluator).__name__,
    )
    return decision


support_agent = Agent(
    llm_model,
    deps_type=TicketDeps,
    output_type=TicketResolution,
    model_settings=ModelSettings(temperature=0),
    defer_model_check=True,
    capabilities=[
        OnlineEvaluation(
            evaluators=[
                # Always runs — cheap (no LLM call).
                ReferenceKind(),
                # Always runs — primary escalation signal.
                escalation_judge(llm_model),
                # Scoped: only on tickets that mention stripe in the input prompt.
                # `inputs` here is the user-prompt string `format_ticket_prompt` built,
                # so a substring check is enough — no extra plumbing required.
                OnlineEvaluator(
                    evaluator=evidence_judge(llm_model),
                    sample_rate=_evidence_judge_predicate,
                ),
                # Sampled: 50% of runs get a quality score. Cuts cost in half while
                # still giving a continuous quality signal to chart over time.
                OnlineEvaluator(
                    evaluator=resolution_quality_score(llm_model),
                    sample_rate=0.5,
                ),
            ]
        )
    ],
)


@support_agent.system_prompt
async def _system_prompt(ctx: RunContext[TicketDeps]) -> str:
    with _prompt_var().get() as resolved:
        return _render_template(resolved.value, {"integrations": INTEGRATIONS_LIST})


@support_agent.tool
async def search_integration_docs(
    ctx: RunContext[TicketDeps],
    query: str,
    systems: list[str],
) -> list[dict]:
    """Search integration documentation for relevant information.

    Args:
        query: Natural language search query about the integration issue.
        systems: List of integration names to search (e.g. ["stripe", "twilio"]).
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
        query = query.where(Ticket.integration == system_filter)

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
async def check_service_status(
    ctx: RunContext[TicketDeps],
    integration: str,
) -> dict:
    """Check live upstream service status.
    Call this to determine if the third-party provider is experiencing issues.

    Args:
        integration: The integration name (e.g. "stripe", "twilio", "sendgrid").
    """
    async with httpx.AsyncClient(transport=ctx.deps.status_service_transport) as client:
        resp = await client.get(
            f"{ctx.deps.status_service_base_url}/api/service-status/{integration}"
        )
        resp.raise_for_status()
        return resp.json()


@support_agent.tool
async def get_escalation_context(
    ctx: RunContext[TicketDeps],
    priority: str,
    integration: str,
) -> dict:
    """Get escalation context for a ticket. Call this when priority is P1 or confidence is low.

    Args:
        priority: The ticket priority (P1, P2, P3).
        integration: The integration name.
    """
    for config in ctx.deps.escalation_configs:
        if config.integration == integration:
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
