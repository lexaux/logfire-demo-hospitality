"""Eval dataset: 8 test cases for the integration support agent."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from evals.evaluators import (
    CategoryMatch,
    PriorityMatch,
    ReferenceKind,
    escalation_judge,
    evidence_judge,
    resolution_quality_score,
)
from src.llm import llm_model
from src.schemas import TicketInput, TicketResolution

# Dataset-level evaluators — run on every case.
#   - CategoryMatch / PriorityMatch: ground-truth comparison against expected_output
#   - escalation_judge / evidence_judge / resolution_quality_score / ReferenceKind:
#     the same evaluators the agent runs online, so offline scores are directly
#     comparable to the live production scores in Logfire.
dataset = Dataset[TicketInput, TicketResolution, None](
    name="integration-support-default",
    evaluators=[
        CategoryMatch(),
        PriorityMatch(),
        escalation_judge(llm_model),
        evidence_judge(llm_model),
        resolution_quality_score(llm_model),
        ReferenceKind(),
    ],
    cases=[
        # 1. Stripe webhook dropping on production traffic → sync_issue, P1, high
        # "all merchants" = outage across the integration = P1
        Case(
            name="stripe_webhook_not_arriving",
            inputs=TicketInput(
                subject="charge.succeeded webhooks not arriving in production",
                description=(
                    "Since this morning we've stopped receiving charge.succeeded webhooks "
                    "from Stripe for all merchants. Payments are completing in the dashboard "
                    "but our system never marks invoices paid. No errors in our logs."
                ),
                integration="stripe",
            ),
            expected_output=TicketResolution(
                category="sync_issue",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 2. Twilio sub-merchant payout equivalent: bulk SMS without 10DLC blocked → not_supported, P1
        # Customer can't ship a launch — agent should flag this clearly as a config requirement
        Case(
            name="twilio_bulk_sms_no_a2p",
            inputs=TicketInput(
                subject="Bulk SMS to US numbers returning 30007 errors",
                description=(
                    "We're trying to send 20,000 notification SMS to US customers via "
                    "Twilio and getting error code 30007 on every send. We have a registered "
                    "phone number but no Messaging Service. This is blocking our launch."
                ),
                integration="twilio",
            ),
            expected_output=TicketResolution(
                category="config",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 3. SendGrid silent suppression drop on ambiguous symptom → config, P2, low (ambiguous)
        Case(
            name="sendgrid_suppression_silent_drop",
            inputs=TicketInput(
                subject="Suppression list import showing wrong count, no error",
                description=(
                    "We uploaded a 50k-row suppression CSV to SendGrid and it shows ~49,700 "
                    "entries afterwards. No error was returned. We can't tell which addresses "
                    "were dropped or why."
                ),
                integration="sendgrid",
            ),
            expected_output=TicketResolution(
                category="bug",
                priority="P2",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 4. Stripe duplicate charge.succeeded webhook → bug, P1, high
        # BUG-S001: idempotency key + retried POST produces dupes
        Case(
            name="stripe_duplicate_webhook",
            inputs=TicketInput(
                subject="Duplicate charge.succeeded webhooks for the same payment",
                description=(
                    "Every time our worker retries a POST to /v1/payment_intents we receive "
                    "two charge.succeeded webhooks with the same idempotency key. This is "
                    "double-counting revenue in our reporting."
                ),
                integration="stripe",
            ),
            expected_output=TicketResolution(
                category="bug",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 5. SendGrid event webhook signature failing with emoji → bug, P2, high
        # BUG-G001: NFC normalization needed
        Case(
            name="sendgrid_signature_emoji",
            inputs=TicketInput(
                subject="Event webhook signature verification failing intermittently",
                description=(
                    "Our SendGrid event webhook handler is returning 401 on roughly 10% of "
                    "events. Same secret as before. Pattern seems to be messages with emoji "
                    "in the subject line."
                ),
                integration="sendgrid",
            ),
            expected_output=TicketResolution(
                category="bug",
                priority="P2",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 6. Twilio Verify OTP delivery delay → sync_issue, P2, low (ambiguous regional)
        # BUG-T003: BR carriers delay >2 min during peak
        Case(
            name="twilio_verify_brazil_delay",
            inputs=TicketInput(
                subject="Verify OTP arriving 2+ minutes late for Brazilian numbers",
                description=(
                    "Customers in Brazil are reporting Twilio Verify OTPs taking 2-3 minutes "
                    "to arrive during peak hours. US and EU numbers are fine. We can't find "
                    "documented delivery SLAs by region."
                ),
                integration="twilio",
            ),
            expected_output=TicketResolution(
                category="sync_issue",
                priority="P2",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 7. Stripe sub-merchant split payouts → not_supported, P3, high
        Case(
            name="stripe_sub_merchant_payouts",
            inputs=TicketInput(
                subject="Cannot split a charge between us and a partner",
                description=(
                    "We want to split each charge between us and a partner using the destination "
                    "parameter on Stripe charges. Our current Stripe account is a Standard account "
                    "and the parameter doesn't seem to work."
                ),
                integration="stripe",
            ),
            expected_output=TicketResolution(
                category="not_supported",
                priority="P3",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 8. SendGrid undocumented inbox-placement targeting → not_supported, P3, low (ambiguous)
        Case(
            name="sendgrid_inbox_targeting_undocumented",
            inputs=TicketInput(
                subject="Force our emails into Gmail Primary instead of Promotions",
                description=(
                    "Our transactional emails are landing in Gmail's Promotions tab instead of "
                    "Primary. We can't find any SendGrid API to override the recipient mailbox "
                    "categorization. Is this supported?"
                ),
                integration="sendgrid",
            ),
            expected_output=TicketResolution(
                category="not_supported",
                priority="P3",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
    ],
)
