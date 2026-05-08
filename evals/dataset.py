"""Eval dataset: 8 test cases for the hospitality support agent."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from evals.evaluators import CategoryMatch, PriorityMatch, escalation_judge
from src.llm import llm_model
from src.schemas import TicketResolution

dataset = Dataset[dict, TicketResolution, None](
    name="hospitality-support-default",
    evaluators=[CategoryMatch(), PriorityMatch()],
    cases=[
        # 1. Mews check-in not triggering message → sync_issue, P1, high
        # "all properties" affected = outage across multiple properties = P1
        Case(
            name="mews_checkin_message_not_triggering",
            inputs={
                "subject": "Guest messages not triggering after Mews check-in",
                "description": (
                    "After a guest checks in via Mews, the automated welcome message "
                    "is not being sent through Canary. This started happening yesterday "
                    "for all properties using Mews. No error in our logs."
                ),
                "pms_system": "mews",
            },
            expected_output=TicketResolution(
                category="sync_issue",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 2. Hostaway bulk rate sync → not_supported, P1, high
        # Agent correctly escalates P1 per system prompt rules
        Case(
            name="hostaway_bulk_rate_sync",
            inputs={
                "subject": "Hostaway bulk rate sync not working",
                "description": (
                    "We need to push rate changes across 50+ listings at once "
                    "through the Hostaway integration. The bulk rate update endpoint "
                    "returns 404. This is blocking our revenue team."
                ),
                "pms_system": "hostaway",
            },
            expected_output=TicketResolution(
                category="not_supported",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
        ),
        # 3. Early check-in upsell silent failure → config, P2, low (ambiguous)
        Case(
            name="mews_early_checkin_upsell_silent_fail",
            inputs={
                "subject": "Early check-in upsell not working, no error shown",
                "description": (
                    "We configured early check-in upsell through Mews but guests "
                    "are not seeing the offer. No errors in the dashboard. We've "
                    "double-checked the configuration and it looks correct."
                ),
                "pms_system": "mews",
            },
            expected_output=TicketResolution(
                category="config",
                priority="P2",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
            evaluators=(escalation_judge(llm_model),),
        ),
        # 4. Webhook firing twice → bug, P1, high
        Case(
            name="mews_webhook_duplicate",
            inputs={
                "subject": "Webhook firing twice on every reservation update",
                "description": (
                    "Every time a reservation is updated in Mews, we receive two "
                    "webhook events instead of one. This is causing duplicate "
                    "processing and double-charging guests for add-ons."
                ),
                "pms_system": "mews",
            },
            expected_output=TicketResolution(
                category="bug",
                priority="P1",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 5. Cloudbeds OTA passthrough missing fields → bug, P2, high
        # BUG-C001: "OTA passthrough missing address field for Expedia bookings"
        Case(
            name="cloudbeds_ota_passthrough_missing",
            inputs={
                "subject": "Cloudbeds OTA reservation passthrough missing guest address",
                "description": (
                    "Reservations coming through Expedia via Cloudbeds are missing "
                    "the guest address field. Other OTA channels seem fine. This "
                    "affects our pre-arrival communication workflow."
                ),
                "pms_system": "cloudbeds",
            },
            expected_output=TicketResolution(
                category="bug",
                priority="P2",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 6. Guest messaging delay >10 min → sync_issue, P2, low (ambiguous)
        # Hostaway docs show Roomkey has "10 min delay" — agent correctly flags sync_issue
        Case(
            name="hostaway_messaging_delay",
            inputs={
                "subject": "Guest messaging delay over 10 minutes on Hostaway",
                "description": (
                    "Messages sent through our platform to Hostaway guests are "
                    "taking over 10 minutes to arrive. We can't find any "
                    "documentation about expected delivery times or rate limits."
                ),
                "pms_system": "hostaway",
            },
            expected_output=TicketResolution(
                category="sync_issue",
                priority="P2",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
            evaluators=(escalation_judge(llm_model),),
        ),
        # 7. Hostaway weekly rates not syncing → not_supported, P3, high
        Case(
            name="hostaway_weekly_rates_not_syncing",
            inputs={
                "subject": "Hostaway weekly/monthly rate tiers not syncing",
                "description": (
                    "We set up weekly and monthly rate tiers in Hostaway but they "
                    "are not appearing in our platform. Only nightly rates come through."
                ),
                "pms_system": "hostaway",
            },
            expected_output=TicketResolution(
                category="not_supported",
                priority="P3",
                confidence="high",
                resolution_suggestion="placeholder",
            ),
        ),
        # 8. Minibar sync not in docs → not_supported, P3, low (ambiguous)
        # Not mentioned in docs at all = not_supported per prompt rules
        Case(
            name="cloudbeds_minibar_sync_undocumented",
            inputs={
                "subject": "Minibar consumption sync from Cloudbeds not documented",
                "description": (
                    "We'd like to sync minibar consumption data from Cloudbeds "
                    "into our guest profile but can't find any documentation. "
                    "Is this supported? If not, what's the workaround?"
                ),
                "pms_system": "cloudbeds",
            },
            expected_output=TicketResolution(
                category="not_supported",
                priority="P3",
                confidence="low",
                resolution_suggestion="placeholder",
                escalation_recommended=True,
            ),
            evaluators=(escalation_judge(llm_model),),
        ),
    ],
)
