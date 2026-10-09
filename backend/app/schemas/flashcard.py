from datetime import datetime
from typing import Literal

from app.config import settings
from app.models.flashcard import BatchStatus, CardStatus
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_WORD_LENGTH = 100
MAX_FIELD_LENGTH = 1000


def clean_words(raw_words: list[str]) -> list[str]:
    """Trim, drop blanks and case-insensitive duplicates, and enforce the per-request limits."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in raw_words:
        word = " ".join(raw.split())
        if not word or word.lower() in seen:
            continue
        if len(word) > MAX_WORD_LENGTH:
            raise ValueError(f"A word must not exceed {MAX_WORD_LENGTH} characters")
        seen.add(word.lower())
        cleaned.append(word)
    if not cleaned:
        raise ValueError("At least one word is required")
    if len(cleaned) > settings.MAX_WORDS_PER_REQUEST:
        raise ValueError(f"At most {settings.MAX_WORDS_PER_REQUEST} words are allowed per request")
    return cleaned


class WordsRequest(BaseModel):
    words: list[str]

    @field_validator("words")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return clean_words(value)


class AIFlashcard(BaseModel):
    """Validated output of the text model."""

    ipa: str = Field(min_length=1, max_length=MAX_FIELD_LENGTH)
    meaning: str = Field(min_length=1, max_length=MAX_FIELD_LENGTH)
    example_target: str = Field(min_length=1, max_length=MAX_FIELD_LENGTH)
    example_meaning: str = Field(min_length=1, max_length=MAX_FIELD_LENGTH)
    image_prompt: str = Field(min_length=1, max_length=MAX_FIELD_LENGTH)

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class CardResponse(BaseModel):
    card_id: str
    word: str
    status: CardStatus
    error: str | None = None
    ipa: str | None = None
    meaning: str | None = None
    example_target: str | None = None
    example_meaning: str | None = None
    has_image: bool = False
    image_url: str | None = None


class AddWordsResponse(BaseModel):
    batch_id: str
    status: BatchStatus
    total: int
    added: int
    skipped: list[str]  # words already in the batch


class BatchResponse(BaseModel):
    batch_id: str
    status: BatchStatus
    total: int
    completed: int
    expires_at: datetime | None  # None until the batch is first downloaded
    cards: list[CardResponse]


RegenerateTarget = Literal["example", "image", "all"]


class CardRegenerateRequest(BaseModel):
    target: RegenerateTarget = "example"
    instruction: str | None = Field(default=None, max_length=300)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
