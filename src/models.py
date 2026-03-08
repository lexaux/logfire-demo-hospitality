import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(128), default="demo-user")
    pms_system: Mapped[str] = mapped_column(String(32), nullable=False)  # mews|cloudbeds|hostaway
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|resolved|escalated

    # AI-generated fields
    ai_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ai_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_resolution_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_docs_referenced: Mapped[list | None] = mapped_column(JSON, nullable=True)
    similar_ticket_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    escalation_recommended: Mapped[bool | None] = mapped_column(nullable=True)

    # For seeded resolved tickets
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
