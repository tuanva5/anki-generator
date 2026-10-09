from datetime import datetime, timedelta, timezone
from enum import Enum

from app.config import settings
from sqlmodel import Field, Relationship, SQLModel


class CardStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BatchStatus(str, Enum):
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def utcnow() -> datetime:
    # SQLite drops tzinfo, so keep every stored datetime naive UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Batch(SQLModel, table=True):
    __tablename__ = "batches"

    batch_id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    # Set on the first download; the retention countdown only starts then
    downloaded_at: datetime | None = Field(default=None, index=True)
    cards: list["Card"] = Relationship(back_populates="batch", cascade_delete=True)

    @property
    def expires_at(self) -> datetime | None:
        if self.downloaded_at is None:
            return None
        return (self.downloaded_at + timedelta(hours=settings.RETENTION_HOURS)).replace(tzinfo=timezone.utc)


class Card(SQLModel, table=True):
    __tablename__ = "cards"

    card_id: str = Field(primary_key=True)
    batch_id: str = Field(foreign_key="batches.batch_id", index=True)
    position: int = Field(default=0)
    word: str
    ipa: str | None = None
    meaning: str | None = None
    example_target: str | None = None
    example_meaning: str | None = None
    image_prompt: str | None = None
    has_image: bool = False
    status: CardStatus = Field(default=CardStatus.PENDING)
    error: str | None = None
    batch: Batch | None = Relationship(back_populates="cards")


def compute_batch_status(cards: list[Card]) -> BatchStatus:
    """Batch status is derived from its cards so it can never drift out of sync."""
    statuses = {card.status for card in cards}
    if statuses & {CardStatus.PENDING, CardStatus.PROCESSING}:
        return BatchStatus.PROCESSING
    if CardStatus.FAILED in statuses:
        return BatchStatus.FAILED
    return BatchStatus.COMPLETED
