from datetime import timedelta

from app.config import settings
from app.models.flashcard import Batch, Card, CardStatus, utcnow
from app.services import storage
from sqlmodel import Session, SQLModel, create_engine, select

# check_same_thread=False lets FastAPI use the connection from different threads
engine = create_engine(f"sqlite:///{settings.DB_FILE}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def fail_interrupted_cards() -> None:
    """Cards left in-flight by a previous server run will never finish; mark them failed."""
    with Session(engine) as session:
        stmt = select(Card).where(Card.status.in_([CardStatus.PENDING, CardStatus.PROCESSING]))  # type: ignore[attr-defined]
        for card in session.exec(stmt).all():
            card.status = CardStatus.FAILED
            card.error = "Generation was interrupted by a server restart"
            session.add(card)
        session.commit()


def clean_old_data(session: Session) -> None:
    """Delete batches downloaded more than the retention period ago, with their images and exports."""
    cutoff = utcnow() - timedelta(hours=settings.RETENTION_HOURS)

    for batch in session.exec(select(Batch).where(Batch.downloaded_at < cutoff)).all():  # type: ignore[operator]
        for card in batch.cards:
            storage.remove_image(card.card_id)
        storage.remove_file(storage.export_path(batch.batch_id))
        session.delete(batch)  # cascades to cards
    session.commit()
