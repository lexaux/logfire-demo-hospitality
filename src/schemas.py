from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel as _BaseModel
from pydantic import Field


class BaseModel(_BaseModel):
    model_config = {"from_attributes": True}


# --- Enums with descriptions ---
class PmsSystem(StrEnum):
    MEWS = "mews"
    CLOUDBEDS = "cloudbeds"
    HOSTAWAY = "hostaway"


class Category(StrEnum):
    BILLING = "billing"
    SYNC_ISSUE = "sync_issue"
    CONFIG = "config"
    NOT_SUPPORTED = "not_supported"
    BUG = "bug"
    UNKNOWN = "unknown"


CATEGORY_DESCRIPTIONS: dict[Category, str] = {
    Category.BILLING: "billing/payment issue",
    Category.SYNC_ISSUE: "data flow missing, delayed, or corrupted — not a documented bug",
    Category.CONFIG: (
        "feature exists but needs user-side setup; docs say 'manual config' or 'requires setup'"
    ),
    Category.NOT_SUPPORTED: "listed as Not Supported in docs, or not mentioned in docs at all",
    Category.BUG: "matches a documented known bug (BUG-xxx); always cite the bug ID",
    Category.UNKNOWN: "ambiguous and no relevant docs, bugs, or similar tickets found",
}


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


PRIORITY_DESCRIPTIONS: dict[Priority, str] = {
    Priority.P1: (
        "financial impact, data loss, or complete outage affecting multiple guests/properties"
    ),
    Priority.P2: "feature degradation with workaround, delayed sync, or single-property scope",
    Priority.P3: "feature not supported, informational inquiry, or cosmetic issue",
}


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CONFIDENCE_DESCRIPTIONS: dict[Confidence, str] = {
    Confidence.HIGH: "clear docs/precedent",
    Confidence.MEDIUM: "partial match",
    Confidence.LOW: "ambiguous/undocumented",
}


class TicketStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


def _enum_description(enum_cls: type[StrEnum], descriptions: dict) -> str:
    return ", ".join(f"{m.value} ({descriptions[m]})" for m in enum_cls)


# Annotated types — description defined once, reused across any model field
CategoryField = Annotated[
    Category, Field(description=_enum_description(Category, CATEGORY_DESCRIPTIONS))
]
PriorityField = Annotated[
    Priority, Field(description=_enum_description(Priority, PRIORITY_DESCRIPTIONS))
]
ConfidenceField = Annotated[
    Confidence, Field(description=_enum_description(Confidence, CONFIDENCE_DESCRIPTIONS))
]


# --- Agent output type ---
class TicketResolution(BaseModel):
    category: CategoryField
    priority: PriorityField
    confidence: ConfidenceField
    resolution_suggestion: str = Field(description="2-4 sentence resolution guidance")
    source_docs_referenced: list[str] = Field(
        default_factory=list, description="List of doc names used"
    )
    similar_ticket_ids: list[int] = Field(
        default_factory=list, description="IDs of similar resolved tickets"
    )
    escalation_recommended: bool = Field(
        default=False, description="Whether this ticket should be escalated"
    )


# --- Agent input type ---
# Source-of-truth shape for what the support agent operates on. Used by:
#   - FastAPI (via TicketCreate subclass, which adds length validation)
#   - evals/dataset.py (static Cases)
#   - evals/curated.py (Logfire-hosted dataset)
class TicketInput(BaseModel):
    subject: str
    description: str
    pms_system: PmsSystem


# --- API request/response ---
class TicketCreate(TicketInput):
    subject: str = Field(min_length=5, max_length=256)
    description: str = Field(min_length=10)


class TicketResponse(BaseModel):
    id: int
    subject: str
    description: str
    pms_system: PmsSystem
    status: TicketStatus
    ai_category: Category | None = None
    ai_priority: Priority | None = None
    ai_confidence: Confidence | None = None
    ai_resolution_suggestion: str | None = None
    source_docs_referenced: list[str] | None = None
    similar_ticket_ids: list[int] | None = None
    escalation_recommended: bool | None = None


# --- Knowledge base validation ---
class DocSection(BaseModel):
    title: str
    items: list[str]


class IntegrationDoc(BaseModel):
    system: PmsSystem
    display_name: str
    supported: list[DocSection] = Field(default_factory=list)
    partial: list[DocSection] = Field(default_factory=list)
    not_supported: list[DocSection] = Field(default_factory=list)
    known_bugs: list[DocSection] = Field(default_factory=list)


class PmsStatus(BaseModel):
    system: PmsSystem
    status: str
    incident: str | None = None
    since: str | None = None


class EscalationEntry(BaseModel):
    pms_system: PmsSystem
    sla_hours: int
    owner_team: str
    currently_degraded: bool = False
    escalation_notes: str = ""


class SeededTicket(BaseModel):
    subject: str
    description: str
    pms_system: PmsSystem
    status: TicketStatus = TicketStatus.RESOLVED
    ai_category: Category
    ai_priority: Priority
    ai_confidence: Confidence
    ai_resolution_suggestion: str
    resolution_notes: str
    source_docs_referenced: list[str] = Field(default_factory=list)
    similar_ticket_ids: list[int] = Field(default_factory=list)
    escalation_recommended: bool = False
