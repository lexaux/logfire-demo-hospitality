"""CLI entry point for running evals.

Usage:
    uv run python -m evals.run_evals                       # metadata: {model: openai:gpt-4o}
    uv run python -m evals.run_evals --tag "new-prompt-v2" # metadata: {..., tag: new-prompt-v2}
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import yaml
from httpx import ASGITransport
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_evals.dataset import set_eval_attribute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.agent import TicketDeps, _prompt_var, format_ticket_prompt, support_agent
from src.config import settings
from src.knowledge import build_doc_chunks, load_integration_docs
from src.main import app
from src.models import Base
from src.schemas import EscalationEntry, TicketInput, TicketResolution
from src.seed import seed_tickets
from src.status_service_app import app as status_service_app

EVAL_BASE_URL = "http://test"

# In-memory SQLite for evals (isolated from production DB)
EVAL_DB_URL = "sqlite+aiosqlite://"


async def _setup_eval_db() -> async_sessionmaker[AsyncSession]:
    """Create an in-memory DB, seed it, and return a session factory."""
    engine = create_async_engine(EVAL_DB_URL, echo=False)
    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        await seed_tickets(session)

    return session_factory


async def main(args: argparse.Namespace):
    # Boot both app lifespans so check_service_status can route via ASGI
    async with (
        app.router.lifespan_context(app),
        status_service_app.router.lifespan_context(status_service_app),
    ):
        # Load knowledge base
        docs = load_integration_docs()
        doc_chunks = build_doc_chunks(docs)

        # Load escalation config
        esc_path = Path("data/escalation_config.yaml")
        with open(esc_path) as f:
            raw = yaml.safe_load(f)
        escalation_configs = [EscalationEntry.model_validate(e) for e in raw]

        # Set up eval DB
        session_factory = await _setup_eval_db()

        # ASGI transport so check_service_status routes to the status app
        status_service_transport = ASGITransport(app=status_service_app)

        async def task_fn(inputs: TicketInput) -> TicketResolution:
            """Run the agent on a single eval case."""
            async with session_factory() as session:
                deps = TicketDeps(
                    db_session=session,
                    doc_chunks=doc_chunks,
                    escalation_configs=escalation_configs,
                    integration=inputs.integration,
                    app_base_url=EVAL_BASE_URL,
                    status_service_base_url=EVAL_BASE_URL,
                    status_service_transport=status_service_transport,
                )
                with _prompt_var().get():
                    result = await support_agent.run(
                        format_ticket_prompt(None, inputs),
                        deps=deps,
                    )
                tools_used = [
                    part.tool_name
                    for msg in result.all_messages()
                    if isinstance(msg, ModelResponse)
                    for part in msg.parts
                    if isinstance(part, ToolCallPart)
                ]
                set_eval_attribute("tools_used", tools_used)
                return result.output

        # Pick the dataset source (static / curated / merged)
        if args.source == "static":
            from evals.dataset import dataset
        elif args.source == "curated":
            from evals.curated import load_curated

            dataset = load_curated()
        else:  # both
            from evals.curated import merged

            dataset = merged()

        meta = {"model": settings.model_name, "source": args.source}
        if args.tag:
            meta["tag"] = args.tag
        report = await dataset.evaluate(
            task_fn,
            max_concurrency=2,
            name=f"integration-support-{args.source}",
            metadata=meta,
        )
        report.print(
            include_output=True,
            include_expected_output=True,
            include_reasons=True,
        )

        # Print tool usage per case
        print("\n  Tool Usage by Case:")
        for case in report.cases:
            tools = case.attributes.get("tools_used", [])
            print(f"    {case.name}: {', '.join(tools) or '(none)'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tag", default="", help="Optional tag added to metadata (e.g. 'new-prompt-v2')"
    )
    parser.add_argument(
        "--source",
        default="static",
        choices=["static", "curated", "both"],
        help="Where cases come from: static (in-repo), curated (Logfire-hosted), or both.",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
