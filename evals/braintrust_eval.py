"""Braintrust eval — the side-by-side counterpart to evals/run_evals.py.

Same 8-case dataset, same *real* agent (4 tools, in-memory DB, ASGI status
service), but results land as a Braintrust **experiment** instead of a Logfire
eval view. The deterministic scorers mirror CategoryMatch / PriorityMatch from
evals/evaluators.py; the LLM judge mirrors evidence_judge, expressed with
Braintrust's autoevals.LLMClassifier so the comparison covers both styles.

Run (needs BRAINTRUST_API_KEY + OPENAI_API_KEY):
    uv run braintrust eval evals/braintrust_eval.py

The `braintrust eval` CLI imports this module and picks up the Eval() call at
import time; there is no __main__ block.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

import yaml
from autoevals.llm import LLMClassifier
from braintrust import Eval
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from evals.dataset import dataset
from src.agent import TicketDeps, format_ticket_prompt, support_agent
from src.config import settings
from src.knowledge import build_doc_chunks, load_integration_docs
from src.llm import llm_model
from src.main import app  # noqa: F401 — import wires logfire + setup_pydantic_ai tracing
from src.models import Base
from src.schemas import EscalationEntry, TicketInput
from src.seed import seed_tickets
from src.status_service_app import app as status_service_app

EVAL_BASE_URL = "http://test"
# In-memory SQLite, isolated from the real tickets.db (same choice as run_evals.py)
EVAL_DB_URL = "sqlite+aiosqlite://"

# Lazy, once-only shared setup. Mutated in place (no `global` rebinding) so the
# heavy boot — app lifespans, knowledge base, seeded DB — happens inside the
# event loop Braintrust drives the tasks on, exactly once across all cases.
_state: dict = {}
_setup_lock = asyncio.Lock()


async def _ensure_setup() -> dict:
    if _state:
        return _state
    async with _setup_lock:
        if _state:
            return _state

        stack = AsyncExitStack()
        # Boot both app lifespans so the agent's check_service_status tool can
        # route to the status microservice over ASGI (mirrors run_evals.py).
        await stack.enter_async_context(app.router.lifespan_context(app))
        await stack.enter_async_context(
            status_service_app.router.lifespan_context(status_service_app)
        )

        doc_chunks = build_doc_chunks(load_integration_docs())

        raw = yaml.safe_load(Path("data/escalation_config.yaml").read_text())
        escalation_configs = [EscalationEntry.model_validate(e) for e in raw]

        engine = create_async_engine(EVAL_DB_URL, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            await seed_tickets(session)

        _state.update(
            stack=stack,  # kept alive for the process; lifespans close on exit
            doc_chunks=doc_chunks,
            escalation_configs=escalation_configs,
            session_factory=session_factory,
            status_transport=ASGITransport(app=status_service_app),
        )
        return _state


async def run_agent(input: dict) -> dict:
    """Braintrust task: run the real support agent on one case's input."""
    state = await _ensure_setup()
    ticket = TicketInput.model_validate(input)
    async with state["session_factory"]() as session:
        deps = TicketDeps(
            db_session=session,
            doc_chunks=state["doc_chunks"],
            escalation_configs=state["escalation_configs"],
            integration=ticket.integration,
            app_base_url=EVAL_BASE_URL,
            status_service_base_url=EVAL_BASE_URL,
            status_service_transport=state["status_transport"],
        )
        result = await support_agent.run(format_ticket_prompt(None, ticket), deps=deps)
        return result.output.model_dump(mode="json")


# --- Deterministic scorers (mirror evals/evaluators.py) -----------------------
# A Braintrust scorer is just a callable; its __name__ is the score's label.
# Return 1.0 (pass) / 0.0 (fail); return None to skip when there's no ground truth.


def category_match(output: dict, expected: dict | None, **_) -> float | None:
    if not expected:
        return None
    return 1.0 if output.get("category") == expected.get("category") else 0.0


def priority_match(output: dict, expected: dict | None, **_) -> float | None:
    """P1 false-negative is a hard fail, matching PriorityMatch."""
    if not expected:
        return None
    exp, act = expected.get("priority"), output.get("priority")
    if exp == "P1" and act != "P1":
        return 0.0
    return 1.0 if act == exp else 0.0


def escalation_match(output: dict, expected: dict | None, **_) -> float | None:
    if not expected:
        return None
    return (
        1.0
        if output.get("escalation_recommended") == expected.get("escalation_recommended")
        else 0.0
    )


# --- LLM judge (mirrors evidence_judge in evals/evaluators.py) -----------------
evidence_judge = LLMClassifier(
    name="EvidenceJudge",
    prompt_template=(
        "You are grading a support agent's resolution for an integration ticket.\n\n"
        "Ticket subject: {{input.subject}}\n"
        "Ticket description: {{input.description}}\n"
        "Integration: {{input.integration}}\n\n"
        "Agent resolution_suggestion: {{output.resolution_suggestion}}\n"
        "source_docs_referenced: {{output.source_docs_referenced}}\n"
        "similar_ticket_ids: {{output.similar_ticket_ids}}\n\n"
        "Does the resolution cite CONCRETE evidence from the knowledge base? "
        "Concrete evidence means at least one of: (a) a bug ID like BUG-S001 / "
        "BUG-T001 / BUG-G001, (b) a named integration doc section, or (c) a "
        "referenced similar ticket id. Answer Y if it cites at least one such "
        "concrete reference, N if it is generic advice with no traceable reference."
    ),
    choice_scores={"Y": 1.0, "N": 0.0},
    # Route the judge through the SAME Pydantic AI gateway the agent uses, instead
    # of autoevals' default Braintrust AI proxy (which 401s unless an LLM provider
    # key is configured in the Braintrust org). Reuses the agent's authenticated
    # client creds so no extra setup is needed.
    base_url=str(llm_model.client.base_url),
    api_key=llm_model.client.api_key,
    model=settings.model_name,
    use_cot=True,
)


def _data() -> list[dict]:
    """Reuse the exact same static cases as the pydantic_evals run."""
    return [
        {
            "input": case.inputs.model_dump(mode="json"),
            "expected": case.expected_output.model_dump(mode="json")
            if case.expected_output
            else None,
            "metadata": {"case": case.name},
        }
        for case in dataset.cases
    ]


Eval(
    "pydantic-ai-test",  # Braintrust project (matches .bt/config.json + main.py)
    data=_data,
    task=run_agent,
    scores=[category_match, priority_match, escalation_match, evidence_judge],
    experiment_name=f"static-{settings.model_name}",
    metadata={"model": settings.model_name, "source": "static", "harness": "braintrust"},
    max_concurrency=2,
)
