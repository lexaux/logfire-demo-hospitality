"""Load the Logfire-hosted curated dataset and merge with the static one.

The curated dataset lives in Logfire (`integration-support-prod-curated`) and is
populated by promoting interesting prod traces in the UI. This module fetches
it as a typed `pydantic_evals.Dataset` and offers a `merged()` helper that
combines hosted + static cases into a single dataset for offline eval runs.
"""

from __future__ import annotations

from logfire.experimental.api_client import LogfireAPIClient
from pydantic_evals import Case, Dataset

from evals.dataset import dataset as static_dataset
from evals.evaluators import (
    CategoryMatch,
    EscalationJudge,
    EvidenceJudge,
    PriorityMatch,
    ReferenceKind,
    ResolutionQualityScore,
)
from src.config import settings
from src.schemas import TicketInput, TicketResolution

CURATED_DATASET_NAME = "ticketing-prod-curated"

# Every evaluator the hosted dataset might reference (by class name). Order
# doesn't matter; this list is just the "menu" for hydration.
_CUSTOM_EVALUATORS = [
    CategoryMatch,
    PriorityMatch,
    EscalationJudge,
    EvidenceJudge,
    ResolutionQualityScore,
    ReferenceKind,
]


def load_curated() -> Dataset[TicketInput, TicketResolution, dict | None]:
    """Fetch the curated dataset from Logfire as a typed Dataset.

    Replaces whatever evaluators were baked into the hosted dataset with the
    canonical set from `evals/dataset.py`. This keeps the curated runs
    apples-to-apples with the static run and with the online evaluators.
    """
    if not settings.logfire_api_key:
        raise RuntimeError(
            "LOGFIRE_API_KEY is not set — required to fetch the curated dataset. "
            "Either set it in .env or run with --source static."
        )
    with LogfireAPIClient(api_key=settings.logfire_api_key) as client:
        ds = client.get_dataset(
            CURATED_DATASET_NAME,
            input_type=TicketInput,
            output_type=TicketResolution,
            metadata_type=dict | None,
            custom_evaluator_types=_CUSTOM_EVALUATORS,
        )
    ds.evaluators = list(static_dataset.evaluators)
    return ds


def merged() -> Dataset[TicketInput, TicketResolution, dict | None]:
    """Return a single Dataset with static + curated cases.

    Curated case names are prefixed with `curated:` to keep them distinct in
    reports. Dataset-level evaluators are taken from the static dataset.
    """
    curated = load_curated()
    cases: list[Case[TicketInput, TicketResolution, dict | None]] = list(static_dataset.cases)
    for c in curated.cases:
        c.name = f"curated:{c.name}" if c.name else "curated:unnamed"
        cases.append(c)
    return Dataset[TicketInput, TicketResolution, dict | None](
        name="integration-support-merged",
        cases=cases,
        evaluators=list(static_dataset.evaluators),
    )
