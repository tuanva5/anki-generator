from app.models.flashcard import Batch, Card, CardStatus

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png"
JPEG = b"\xff\xd8\xff" + b"fake-jpeg"


def add_words(client, words):
    # The test client runs background tasks before returning, so generation is finished afterwards
    response = client.post("/flashcards/batch", json={"words": words})
    assert response.status_code == 202, response.text
    return response.json()


def current(client):
    return client.get("/flashcards/batch/current")


def card_url(batch_id, card_id):
    return f"/flashcards/batch/{batch_id}/card/{card_id}"


def insert_pending_batch(db) -> tuple[str, str]:
    """A batch whose single card is still waiting for the AI."""
    db.add(Batch(batch_id="pending-batch"))
    db.add(Card(card_id="pending-card", batch_id="pending-batch", word="waiting", status=CardStatus.PENDING))
    db.commit()
    return "pending-batch", "pending-card"
