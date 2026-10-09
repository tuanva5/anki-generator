import io
import json
import zipfile
from datetime import timedelta

from app.models.flashcard import Batch, Card, CardStatus, utcnow
from helpers import JPEG, add_words, card_url, current, insert_pending_batch


def test_no_current_batch(client):
    assert current(client).status_code == 404


def test_words_are_cleaned_and_generated(client):
    result = add_words(client, ["  apple ", "Apple", "give   up", ""])
    assert (result["added"], result["total"], result["skipped"]) == (2, 2, [])

    response = current(client)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert [c["word"] for c in body["cards"]] == ["apple", "give up"]
    assert all(c["has_image"] and c["image_url"] for c in body["cards"])


def test_adding_words_appends_to_current_batch_and_skips_duplicates(client):
    first = add_words(client, ["apple", "pear"])
    second = add_words(client, ["PEAR", "kiwi"])

    assert second["batch_id"] == first["batch_id"]
    assert (second["added"], second["skipped"], second["total"]) == (1, ["PEAR"], 3)
    assert [c["word"] for c in current(client).json()["cards"]] == ["apple", "pear", "kiwi"]


def test_request_validation(client):
    assert client.post("/flashcards/batch", json={"words": []}).status_code == 422
    assert client.post("/flashcards/batch", json={"words": [" ", ""]}).status_code == 422
    assert client.post("/flashcards/batch", json={"words": ["x" * 101]}).status_code == 422
    # MAX_WORDS_PER_REQUEST is 5 in tests
    assert client.post("/flashcards/batch", json={"words": list("abcdef")}).status_code == 422


def test_batch_size_cap(client):
    add_words(client, list("abcde"))
    response = client.post("/flashcards/batch", json={"words": ["f", "g"]})  # cap is 6
    assert response.status_code == 422
    assert current(client).json()["total"] == 5


def test_adding_is_rejected_while_batch_is_generating(client, db):
    batch_id, _ = insert_pending_batch(db)

    for response in (
        client.post("/flashcards/batch", json={"words": ["new"]}),
        client.post("/flashcards/batch/upload", files={"file": ("w.txt", b"new")}),
    ):
        assert response.status_code == 409
        assert response.json()["detail"]["batch_id"] == batch_id

    polled = current(client)
    assert polled.status_code == 202
    assert polled.json()["status"] == "PROCESSING"
    assert polled.json()["cards"][0]["meaning"] is None


def test_failed_cards_hide_content_and_do_not_block_adding(client, ai):
    ai.fail_words = {"bad"}
    add_words(client, ["good", "bad"])

    response = current(client)
    body = response.json()
    assert response.status_code == 202
    assert body["status"] == "FAILED"
    assert body["completed"] == 1
    assert [(c["word"], c["status"], c["meaning"]) for c in body["cards"]] == [
        ("good", "COMPLETED", None),
        ("bad", "FAILED", None),
    ]
    assert body["cards"][1]["error"]

    assert client.post("/flashcards/batch", json={"words": ["next"]}).status_code == 202


def test_image_failure_does_not_fail_the_card(client, ai):
    ai.fail_images = True
    add_words(client, ["apple"])

    card = current(client).json()
    assert card["cards"][0]["status"] == "COMPLETED"
    assert card["cards"][0]["has_image"] is False
    assert card["cards"][0]["image_url"] is None


def test_image_is_served_with_its_real_format(client, ai):
    ai.image_bytes = JPEG
    add_words(client, ["apple"])
    body = current(client).json()
    image = client.get(body["cards"][0]["image_url"])

    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "no-cache"


def test_delete_card(client, ai):
    add_words(client, ["apple", "pear"])
    body = current(client).json()
    batch_id, apple = body["batch_id"], body["cards"][0]

    assert client.delete(card_url(batch_id, apple["card_id"])).status_code == 204
    assert client.get(apple["image_url"]).status_code == 404
    assert client.delete(card_url(batch_id, apple["card_id"])).status_code == 404
    assert [c["word"] for c in current(client).json()["cards"]] == ["pear"]
    assert client.delete(card_url("other-batch", body["cards"][1]["card_id"])).status_code == 404


def test_delete_is_rejected_while_card_is_processing(client, db):
    batch_id, card_id = insert_pending_batch(db)
    card = db.get(Card, card_id)
    card.status = CardStatus.PROCESSING
    db.add(card)
    db.commit()

    assert client.delete(card_url(batch_id, card_id)).status_code == 409


# ---- upload ----


def test_upload_text_file_one_word_per_line(client):
    files = {"file": ("words.txt", b"\xef\xbb\xbfapple\r\n  give   up \n\npear, ripe\nApple\n")}
    response = client.post("/flashcards/batch/upload", files=files)

    assert response.status_code == 202
    assert [c["word"] for c in current(client).json()["cards"]] == ["apple", "give up", "pear, ripe"]


def test_upload_csv_uses_first_column_and_skips_header(client):
    content = b'Word,Note\napple,x\n"give up, phrase",y\n\npear,z\n'
    response = client.post("/flashcards/batch/upload", files={"file": ("words.csv", content)})

    assert response.status_code == 202
    assert [c["word"] for c in current(client).json()["cards"]] == ["apple", "give up, phrase", "pear"]


def test_upload_rejections(client):
    def upload(data, name="w.txt"):
        return client.post("/flashcards/batch/upload", files={"file": (name, data)})

    assert upload(b" \n\n").status_code == 422
    assert upload(b"\xff\xfe\x00bad").status_code == 422
    assert upload(b"x" * 2000).status_code == 413  # MAX_UPLOAD_BYTES is 1000 in tests
    assert upload("\n".join("abcdefg").encode()).status_code == 422  # 7 words, limit 5
    assert client.post("/flashcards/batch/upload").status_code == 422


# ---- download and expiry ----


def test_download_builds_apkg_and_starts_expiry_once(client, db):
    add_words(client, ["apple", "<b>pear</b>"])
    batch_id = current(client).json()["batch_id"]
    assert current(client).json()["expires_at"] is None

    response = client.get("/flashcards/batch/current/download")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "collection.anki2" in archive.namelist()
    assert sorted(json.loads(archive.read("media")).values())[0].endswith(".png")

    first_expiry = current(client).json()["expires_at"]
    assert first_expiry is not None
    client.get("/flashcards/batch/current/download")
    assert current(client).json()["expires_at"] == first_expiry
    assert db.get(Batch, batch_id).downloaded_at is not None


def test_download_requires_a_complete_batch(client, ai, db):
    assert client.get("/flashcards/batch/current/download").status_code == 404

    ai.fail_words = {"bad"}
    add_words(client, ["good", "bad"])
    assert client.get("/flashcards/batch/current/download").status_code == 409
    assert current(client).json()["expires_at"] is None


def test_download_of_empty_batch_is_rejected(client):
    add_words(client, ["apple"])
    body = current(client).json()
    client.delete(card_url(body["batch_id"], body["cards"][0]["card_id"]))
    assert client.get("/flashcards/batch/current/download").status_code == 409


def test_adding_words_after_download_clears_the_countdown(client):
    add_words(client, ["apple"])
    client.get("/flashcards/batch/current/download")
    assert current(client).json()["expires_at"] is not None

    add_words(client, ["pear"])
    assert current(client).json()["expires_at"] is None


def test_adding_only_duplicates_keeps_the_countdown(client):
    add_words(client, ["apple"])
    client.get("/flashcards/batch/current/download")

    assert add_words(client, ["apple"])["added"] == 0
    assert current(client).json()["expires_at"] is not None


def test_batch_is_removed_a_day_after_download_only(client, db):
    add_words(client, ["apple"])
    batch_id = current(client).json()["batch_id"]
    batch = db.get(Batch, batch_id)

    # Not downloaded: never expires, however old
    batch.created_at = utcnow() - timedelta(days=30)
    db.add(batch)
    db.commit()
    assert current(client).status_code == 200

    client.get("/flashcards/batch/current/download")
    batch = db.get(Batch, batch_id)
    batch.downloaded_at = utcnow() - timedelta(hours=23)
    db.add(batch)
    db.commit()
    assert current(client).status_code == 200

    db.expire_all()
    batch = db.get(Batch, batch_id)
    batch.downloaded_at = utcnow() - timedelta(hours=25)
    db.add(batch)
    db.commit()
    assert current(client).status_code == 404
    assert client.get(f"/flashcards/batch/{batch_id}").status_code == 404
