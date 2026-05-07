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

from src.agent import TicketDeps, support_agent
from src.config import settings
from src.knowledge import build_doc_chunks, load_integration_docs
from src.main import app
from src.models import Base
from src.pms_status_app import app as pms_status_app
from src.schemas import EscalationEntry, TicketResolution
from src.seed import seed_tickets

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
    # Boot both app lifespans so check_pms_status can route via ASGI
    async with (
        app.router.lifespan_context(app),
        pms_status_app.router.lifespan_context(pms_status_app),
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

        # ASGI transport so check_pms_status routes to the PMS status app
        pms_status_transport = ASGITransport(app=pms_status_app)

        async def task_fn(inputs: dict) -> TicketResolution:
            """Run the agent on a single eval case."""
            async with session_factory() as session:
                deps = TicketDeps(
                    db_session=session,
                    doc_chunks=doc_chunks,
                    escalation_configs=escalation_configs,
                    pms_system=inputs["pms_system"],
                    app_base_url=EVAL_BASE_URL,
                    pms_status_base_url=EVAL_BASE_URL,
                    pms_status_transport=pms_status_transport,
                )
                prompt = (
                    f"PMS: {inputs['pms_system']}\n"
                    f"Subject: {inputs['subject']}\n"
                    f"Description: {inputs['description']}"
                )
                result = await support_agent.run(prompt, deps=deps)
                tools_used = [
                    part.tool_name
                    for msg in result.all_messages()
                    if isinstance(msg, ModelResponse)
                    for part in msg.parts
                    if isinstance(part, ToolCallPart)
                ]
                set_eval_attribute("tools_used", tools_used)
                return result.output

        # Import dataset and run
        from evals.dataset import dataset

        meta = {"model": settings.model_name}
        if args.tag:
            meta["tag"] = args.tag
        report = await dataset.evaluate(
            task_fn,
            max_concurrency=2,
            name="default-hospitality",
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
    args = parser.parse_args()
    asyncio.run(main(args))
