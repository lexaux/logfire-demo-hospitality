"""Custom evaluators for the hospitality support agent."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic_ai.models import Model
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext, LLMJudge
from pydantic_evals.evaluators.common import OutputConfig

from src.schemas import TicketResolution


@dataclass
class EscalationJudge(LLMJudge):
    """Distinct class so the span attribute `gen_ai.evaluation.name` = 'EscalationJudge'."""


@dataclass
class EvidenceJudge(LLMJudge):
    """Distinct class so the span attribute `gen_ai.evaluation.name` = 'EvidenceJudge'."""


@dataclass
class ResolutionQualityScore(LLMJudge):
    """Scored (0.0–1.0) judge of resolution quality — not boolean pass/fail."""


class CategoryMatch(Evaluator[dict, TicketResolution, None]):
    """Check if the agent's category matches the expected category."""

    def evaluate(self, ctx: EvaluatorContext[dict, TicketResolution, None]) -> EvaluationReason:
        if ctx.expected_output is None:
            return EvaluationReason(value=True, reason="No expected output to compare")
        match = ctx.output.category == ctx.expected_output.category
        return EvaluationReason(
            value=match,
            reason=f"expected={ctx.expected_output.category}, got={ctx.output.category}",
        )


_URL_RE = re.compile(r"https?://\S+")
_BUG_ID_RE = re.compile(r"\bBUG-[A-Z]\d+\b")
_TICKET_ID_RE = re.compile(r"#\d+|\bticket[\s_-]?#?\d+\b", re.IGNORECASE)


class ReferenceKind(Evaluator[dict, TicketResolution, None]):
    """Categorical evaluator: returns a compound label listing every reference kind
    found in the resolution, sorted and `+`-joined (e.g. `bug_id+url`).

    Logfire renders the cell as the most-common combination with a +N badge for
    other distinct combinations seen across runs. Possible labels: `bug_id`,
    `ticket_ref`, `url`, joined as needed; `none` if nothing matches.
    """

    def evaluate(self, ctx: EvaluatorContext[dict, TicketResolution, None]) -> str:
        text = ctx.output.resolution_suggestion or ""
        labels: list[str] = []
        if _BUG_ID_RE.search(text):
            labels.append("bug_id")
        if _TICKET_ID_RE.search(text) or ctx.output.similar_ticket_ids:
            labels.append("ticket_ref")
        if _URL_RE.search(text):
            labels.append("url")
        return "+".join(labels) if labels else "none"


class PriorityMatch(Evaluator[dict, TicketResolution, None]):
    """Check if the agent's priority matches expected priority.

    P1 false negatives always fail with a special reason.
    """

    def evaluate(self, ctx: EvaluatorContext[dict, TicketResolution, None]) -> EvaluationReason:
        if ctx.expected_output is None:
            return EvaluationReason(value=True, reason="No expected output to compare")
        expected = ctx.expected_output.priority
        actual = ctx.output.priority
        if expected == "P1" and actual != "P1":
            return EvaluationReason(value=False, reason="P1 miss — classified as " + actual)
        match = actual == expected
        return EvaluationReason(
            value=match,
            reason=f"expected={expected}, got={actual}",
        )


def escalation_judge(model: Model | str) -> LLMJudge:
    """LLM judge for escalation appropriateness on ambiguous cases."""
    return EscalationJudge(
        model=model,
        rubric=(
            "The agent's confidence is low or the issue is ambiguous. "
            "Evaluate whether escalation_recommended is appropriate given the context. "
            "If the issue is undocumented or the agent cannot find clear evidence, "
            "escalation should be recommended. Return True if the escalation decision is correct."
        ),
        include_input=True,
        include_expected_output=True,
    )


def evidence_judge(model: Model | str) -> LLMJudge:
    """LLM judge: does resolution_suggestion cite a concrete doc section or bug ID?

    Catches prompt regressions where the agent stops grounding its answer in the
    knowledge base. Designed for online use against real traffic.
    """
    return EvidenceJudge(
        model=model,
        rubric=(
            "Evaluate whether the agent's `resolution_suggestion` cites concrete evidence "
            "from the knowledge base. Concrete evidence means at least one of: "
            "(a) a bug ID like BUG-M001 / BUG-C001 / BUG-H001, "
            "(b) a named integration doc section (e.g. 'Mews webhooks', 'Cloudbeds OTA passthrough'), "
            "(c) a referenced similar ticket id. "
            "Return True if the resolution cites at least one such concrete piece of evidence. "
            "Return False if it is generic advice with no traceable reference."
        ),
        include_input=True,
        include_expected_output=False,
    )


def resolution_quality_score(model: Model | str) -> LLMJudge:
    """Scored LLM judge (0.0–1.0) of overall resolution quality.

    Unlike the boolean judges, this produces a continuous score so we can track
    quality drift over time, not just pass/fail. The model is asked to grade on:
    actionability, specificity, and correct grounding to the PMS/issue context.
    """
    return ResolutionQualityScore(
        model=model,
        rubric=(
            "Grade the agent's `resolution_suggestion` on a continuous 0.0–1.0 scale "
            "based on three criteria: "
            "(1) Actionability — does it tell the support team a concrete next step? "
            "(2) Specificity — is it tailored to the ticket's PMS system and symptom, "
            "or generic boilerplate? "
            "(3) Grounding — does it reflect real integration constraints (bug IDs, "
            "doc sections, vendor status) rather than hallucinated capabilities? "
            "Scoring guide: "
            "0.0 = wrong or harmful advice; "
            "0.25 = generic non-answer; "
            "0.5 = partially correct but missing key context; "
            "0.75 = correct and actionable but lightly grounded; "
            "1.0 = correct, specific, and well-grounded. "
            "Set `pass` to true iff score >= 0.5 (it will be ignored — we report the score)."
        ),
        include_input=True,
        include_expected_output=False,
        score=OutputConfig(include_reason=True),
        assertion=False,
    )
