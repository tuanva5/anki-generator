import asyncio
import logging
import uuid

from app.config import settings
from app.database import clean_old_data, engine
from app.models.flashcard import Batch, BatchStatus, Card, CardStatus, compute_batch_status
from app.schemas.flashcard import AIFlashcard, RegenerateTarget
from app.services import storage
from app.services.ai_service import AIGenerationError, ai_service
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(max(1, settings.GENERATION_CONCURRENCY))


class BatchBusyError(Exception):
    def __init__(self, batch_id: str):
        super().__init__("The current batch is still being generated")
        self.batch_id = batch_id


class BatchFullError(Exception):
    pass


def get_current_batch(session: Session) -> Batch | None:
    """The single live batch; expired ones are purged first so they never count as current."""
    clean_old_data(session)
    return session.exec(select(Batch).order_by(Batch.created_at.desc())).first()  # type: ignore[attr-defined]


def add_words(session: Session, words: list[str]) -> tuple[Batch, list[str], list[str]]:
    """Append words to the current batch (creating it if none) and return (batch, new card ids, skipped words)."""
    batch = get_current_batch(session)
    cards: list[Card] = []
    if batch is None:
        batch = Batch(batch_id=uuid.uuid4().hex)
        session.add(batch)
    else:
        cards = get_cards(session, batch.batch_id)
        if compute_batch_status(cards) == BatchStatus.PROCESSING:
            raise BatchBusyError(batch.batch_id)

    existing = {c.word.lower() for c in cards}
    new_words = [w for w in words if w.lower() not in existing]
    skipped = [w for w in words if w.lower() in existing]
    if len(cards) + len(new_words) > settings.MAX_CARDS_PER_BATCH:
        session.rollback()
        raise BatchFullError(f"A batch can hold at most {settings.MAX_CARDS_PER_BATCH} cards")

    start = max((c.position for c in cards), default=-1) + 1
    new_ids = []
    for offset, word in enumerate(new_words):
        card = Card(card_id=uuid.uuid4().hex, batch_id=batch.batch_id, position=start + offset, word=word)
        session.add(card)
        new_ids.append(card.card_id)
    if new_ids:
        batch.downloaded_at = None  # new cards have not been downloaded yet, so stop the expiry countdown
    session.commit()
    session.refresh(batch)
    return batch, new_ids, skipped


def get_cards(session: Session, batch_id: str) -> list[Card]:
    return list(session.exec(select(Card).where(Card.batch_id == batch_id).order_by(Card.position)).all())  # type: ignore[arg-type]


async def _generate_image(image_prompt: str) -> bytes | None:
    if not settings.GENERATE_IMAGES:
        return None
    try:
        return await ai_service.generate_image(image_prompt)
    except AIGenerationError as e:
        # A card is still useful without its illustration
        logger.warning("Image generation failed: %s", e)
        return None


def _mark_failed(card_id: str, error: str) -> None:
    with Session(engine) as session:
        card = session.get(Card, card_id)
        if card is None:
            return
        card.status = CardStatus.FAILED
        card.error = error
        session.add(card)
        session.commit()


def _apply_full_content(card: Card, data: AIFlashcard, image: bytes | None) -> None:
    card.ipa = data.ipa
    card.meaning = data.meaning
    card.example_target = data.example_target
    card.example_meaning = data.example_meaning
    card.image_prompt = data.image_prompt
    if image:
        storage.save_image(card.card_id, image)
        card.has_image = True
    card.status = CardStatus.COMPLETED
    card.error = None


async def generate_card(card_id: str) -> None:
    """Generate all content of one card; never raises so one bad word cannot sink a batch."""
    async with _semaphore:
        try:
            with Session(engine) as session:
                card = session.get(Card, card_id)
                if card is None:  # removed by the user in the meantime
                    return
                word = card.word
                card.status = CardStatus.PROCESSING
                session.add(card)
                session.commit()

            data = await ai_service.generate_flashcard(word)
            image = await _generate_image(data.image_prompt)

            with Session(engine) as session:
                card = session.get(Card, card_id)
                if card is None:
                    return
                _apply_full_content(card, data, image)
                session.add(card)
                session.commit()
        except AIGenerationError as e:
            _mark_failed(card_id, str(e))
        except Exception:
            logger.exception("Unexpected error while generating card %s", card_id)
            _mark_failed(card_id, "Unexpected error while generating this card")


async def process_cards(card_ids: list[str]) -> None:
    await asyncio.gather(*(generate_card(card_id) for card_id in card_ids))


async def regenerate_card(
    session: Session, card: Card, target: RegenerateTarget, instruction: str | None
) -> None:
    """Regenerate part or all of a card; a failed card has no content so it is always regenerated fully.

    The card is marked PROCESSING meanwhile (blocking uploads and downloads) and restored on error.
    """
    previous_status, previous_error = card.status, card.error
    had_content = previous_status == CardStatus.COMPLETED
    word, example, image_prompt = card.word, card.example_target, card.image_prompt

    card.status = CardStatus.PROCESSING
    session.add(card)
    session.commit()

    data: AIFlashcard | None = None
    image: bytes | None = None
    try:
        async with _semaphore:
            if not had_content or target == "all":
                data = await ai_service.generate_flashcard(
                    word, instruction, previous_example=example if had_content else None
                )
                image = await _generate_image(data.image_prompt)
            elif target == "example":
                data = await ai_service.generate_flashcard(word, instruction, previous_example=example)
            else:
                if instruction:
                    image_prompt = await ai_service.refine_image_prompt(word, image_prompt or word, instruction)
                image = await ai_service.generate_image(image_prompt or word)
    except Exception:
        card.status, card.error = previous_status, previous_error
        session.add(card)
        session.commit()
        raise

    if data and (not had_content or target == "all"):
        _apply_full_content(card, data, image)
    elif data:
        card.example_target = data.example_target
        card.example_meaning = data.example_meaning
    else:
        assert image is not None
        card.image_prompt = image_prompt
        storage.save_image(card.card_id, image)
        card.has_image = True
    card.status = CardStatus.COMPLETED
    card.error = None
    session.add(card)
    session.commit()
    session.refresh(card)
