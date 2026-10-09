import csv
import io
import logging

from app.config import settings
from app.database import get_session
from app.models.flashcard import Batch, BatchStatus, Card, CardStatus, compute_batch_status, utcnow
from app.schemas.flashcard import (
    AddWordsResponse,
    BatchResponse,
    CardRegenerateRequest,
    CardResponse,
    WordsRequest,
    clean_words,
)
from app.services import flashcard_service, storage
from app.services.ai_service import AIGenerationError
from app.services.anki_service import anki_service
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flashcards", tags=["Flashcards"])


def _get_batch(session: Session, batch_id: str) -> Batch:
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


def _get_card(session: Session, batch_id: str, card_id: str) -> Card:
    _get_batch(session, batch_id)
    card = session.get(Card, card_id)
    if card is None or card.batch_id != batch_id:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _card_response(card: Card, full: bool = True) -> CardResponse:
    if not full:
        return CardResponse(card_id=card.card_id, word=card.word, status=card.status, error=card.error)
    return CardResponse(
        card_id=card.card_id,
        word=card.word,
        status=card.status,
        error=card.error,
        ipa=card.ipa,
        meaning=card.meaning,
        example_target=card.example_target,
        example_meaning=card.example_meaning,
        has_image=card.has_image,
        image_url=f"/flashcards/batch/{card.batch_id}/card/{card.card_id}/image" if card.has_image else None,
    )


def _add_words(session: Session, words: list[str]):
    try:
        return flashcard_service.add_words(session, words)
    except flashcard_service.BatchBusyError as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "batch_id": e.batch_id})
    except flashcard_service.BatchFullError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _batch_response(session: Session, batch: Batch, response: Response) -> BatchResponse:
    cards = flashcard_service.get_cards(session, batch.batch_id)
    status = compute_batch_status(cards)
    ready = status == BatchStatus.COMPLETED

    if not ready:
        response.status_code = 202
    return BatchResponse(
        batch_id=batch.batch_id,
        status=status,
        total=len(cards),
        completed=sum(c.status == CardStatus.COMPLETED for c in cards),
        expires_at=batch.expires_at,
        cards=[_card_response(c, full=ready) for c in cards],
    )


def _queue_words(words: list[str], background_tasks: BackgroundTasks, session: Session) -> AddWordsResponse:
    batch, new_ids, skipped = _add_words(session, words)
    if new_ids:
        background_tasks.add_task(flashcard_service.process_cards, new_ids)
    cards = flashcard_service.get_cards(session, batch.batch_id)
    return AddWordsResponse(
        batch_id=batch.batch_id,
        status=compute_batch_status(cards),
        total=len(cards),
        added=len(new_ids),
        skipped=skipped,
    )


@router.post("/batch", response_model=AddWordsResponse, status_code=202)
async def add_words(payload: WordsRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Add words to the current batch (created if none) and generate in the background; 409 while it is still generating."""
    return _queue_words(payload.words, background_tasks, session)


def _words_from_file(filename: str, text: str) -> list[str]:
    if filename.lower().endswith(".csv"):
        # First column of each row; a header cell named "word"/"words" is skipped
        cells = [row[0] for row in csv.reader(io.StringIO(text)) if row]
        if cells and cells[0].strip().lower() in ("word", "words"):
            cells = cells[1:]
        return clean_words(cells)
    return clean_words(text.splitlines())


@router.post("/batch/upload", response_model=AddWordsResponse, status_code=202)
async def upload_words(file: UploadFile, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Same as POST /batch but from a UTF-8 file: .csv uses the first column, anything else one word or phrase per line."""
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File must not exceed {settings.MAX_UPLOAD_BYTES} bytes")
    try:
        words = _words_from_file(file.filename or "", data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 text")
    except (ValueError, csv.Error) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _queue_words(words, background_tasks, session)


@router.get("/batch/current", response_model=BatchResponse)
async def get_current_batch(response: Response, session: Session = Depends(get_session)):
    """Same payload as the by-id endpoint; poll this to follow progress. 404 when no batch exists."""
    batch = flashcard_service.get_current_batch(session)
    if batch is None:
        raise HTTPException(status_code=404, detail="No current batch")
    return _batch_response(session, batch, response)


@router.get("/batch/current/download")
async def download_current_batch(session: Session = Depends(get_session)):
    """Build the .apkg from server-side data. The first download starts the retention countdown."""
    batch = flashcard_service.get_current_batch(session)
    if batch is None:
        raise HTTPException(status_code=404, detail="No current batch")
    cards = flashcard_service.get_cards(session, batch.batch_id)
    if compute_batch_status(cards) != BatchStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Every card must be generated before downloading; regenerate or delete the others")
    if not cards:
        raise HTTPException(status_code=409, detail="Batch has no cards to download")

    path = anki_service.create_apkg_package(batch.batch_id, cards)
    if batch.downloaded_at is None:
        batch.downloaded_at = utcnow()
        session.add(batch)
        session.commit()
    return FileResponse(path, filename="flashcards.apkg", media_type="application/octet-stream")


@router.get("/batch/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: str, response: Response, session: Session = Depends(get_session)):
    """200 with full card data once every card is generated, otherwise 202 with per-card progress only."""
    return _batch_response(session, _get_batch(session, batch_id), response)


@router.get("/batch/{batch_id}/card/{card_id}/image")
async def get_card_image(batch_id: str, card_id: str, session: Session = Depends(get_session)):
    card = _get_card(session, batch_id, card_id)
    path = storage.find_image(card.card_id) if card.has_image else None
    if path is None:
        raise HTTPException(status_code=404, detail="Card has no image")
    # The file is replaced on regeneration while the URL stays the same, so make browsers revalidate
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.patch("/batch/{batch_id}/card/{card_id}", response_model=CardResponse)
async def regenerate_card(
    batch_id: str,
    card_id: str,
    payload: CardRegenerateRequest | None = None,
    session: Session = Depends(get_session),
):
    """Regenerate the example sentence (default), the image, or everything; an optional instruction guides the AI.

    A failed card is always regenerated fully.
    """
    card = _get_card(session, batch_id, card_id)

    if card.status in (CardStatus.PENDING, CardStatus.PROCESSING):
        raise HTTPException(status_code=409, detail="Card is still being generated")

    payload = payload or CardRegenerateRequest()
    if payload.target == "image" and card.status == CardStatus.COMPLETED and not settings.GENERATE_IMAGES:
        raise HTTPException(status_code=409, detail="Image generation is disabled")

    try:
        await flashcard_service.regenerate_card(session, card, payload.target, payload.instruction or None)
    except AIGenerationError as e:
        logger.error("AI regeneration failed for card %s: %s", card_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    return _card_response(card)


@router.delete("/batch/{batch_id}/card/{card_id}", status_code=204)
async def delete_card(batch_id: str, card_id: str, session: Session = Depends(get_session)):
    card = _get_card(session, batch_id, card_id)
    if card.status == CardStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Card is being generated; try again when it finishes")
    storage.remove_image(card.card_id)
    session.delete(card)
    session.commit()
    return Response(status_code=204)
