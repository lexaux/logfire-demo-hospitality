"""Push the local static eval dataset to Logfire as the curated dataset.

Usage:
    uv run python -m evals.push_curated                  # uses CURATED_DATASET_NAME
    uv run python -m evals.push_curated --name foo       # override

Per-case evaluators that hold an LLM model object (e.g. `escalation_judge(llm_model)`)
are not picklable and will be stripped before upload. The dataset-level evaluators
on the static dataset are kept.
"""

from __future__ import annotations

import argparse
import copy

from logfire.experimental.api_client import LogfireAPIClient
from pydantic_evals import Dataset

from evals.curated import CURATED_DATASET_NAME
from evals.dataset import dataset as static_dataset
from src.config import settings
from src.schemas import TicketInput, TicketResolution


def main(name: str) -> None:
    if not settings.logfire_api_key:
        raise SystemExit("LOGFIRE_API_KEY is not set — required to push to Logfire.")

    # Strip per-case evaluators that hold an unpicklable LLM model object.
    cases = []
    for c in static_dataset.cases:
        cc = copy.copy(c)
        cc.evaluators = ()
        cases.append(cc)

    upload = Dataset[TicketInput, TicketResolution, dict | None](
        name=name,
        cases=cases,
        evaluators=list(static_dataset.evaluators),
    )

    with LogfireAPIClient(api_key=settings.logfire_api_key) as client:
        client.push_dataset(upload)

    print(f"Pushed {len(cases)} cases to Logfire dataset {name!r}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name",
        default=CURATED_DATASET_NAME,
        help=f"Dataset name on Logfire (default: {CURATED_DATASET_NAME})",
    )
    args = parser.parse_args()
    main(args.name)
