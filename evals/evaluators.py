"""Custom evaluators for the hospitality support agent."""

from __future__ import annotations

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext, LLMJudge

from src.schemas import TicketResolution


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


def escalation_judge() -> LLMJudge:
    """LLM judge for escalation appropriateness on ambiguous cases."""
    return LLMJudge(
        rubric=(
            "The agent's confidence is low or the issue is ambiguous. "
            "Evaluate whether escalation_recommended is appropriate given the context. "
            "If the issue is undocumented or the agent cannot find clear evidence, "
            "escalation should be recommended. Return True if the escalation decision is correct."
        ),
        include_input=True,
        include_expected_output=True,
    )
