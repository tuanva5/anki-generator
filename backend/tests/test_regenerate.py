import pytest
from app.config import settings
from helpers import JPEG, PNG, add_words, card_url, current, insert_pending_batch


@pytest.fixture
def card(client):
    """One finished card; returns (card dict, patch url, current image bytes getter)."""
    add_words(client, ["apple"])
    body = current(client).json()
    data = body["cards"][0]
    return data, card_url(body["batch_id"], data["card_id"])


def image_of(client, data):
    return client.get(data["image_url"]).content


def test_default_target_regenerates_only_the_example(client, card):
    data, url = card
    response = client.patch(url)

    assert response.status_code == 200
    body = response.json()
    assert body["example_target"] != data["example_target"]
    assert body["meaning"] == data["meaning"]
    assert body["ipa"] == data["ipa"]
    assert image_of(client, body) == PNG


def test_example_regeneration_follows_the_instruction(client, card):
    _, url = card
    response = client.patch(url, json={"target": "example", "instruction": "formal tone"})
    assert response.json()["example_target"].endswith("formal tone")


def test_image_target_regenerates_image_with_stored_prompt(client, ai, card):
    data, url = card
    ai.image_bytes = JPEG
    response = client.patch(url, json={"target": "image"})

    assert response.status_code == 200
    assert response.json()["meaning"] == data["meaning"]
    assert ai.image_prompts[-1] == "prompt-1"  # the prompt stored at creation
    image = client.get(data["image_url"])
    assert image.content == JPEG
    assert image.headers["content-type"] == "image/jpeg"  # format changed, old file replaced


def test_image_instruction_rewrites_and_persists_the_prompt(client, ai, card):
    _, url = card
    client.patch(url, json={"target": "image", "instruction": "cartoon"})
    assert ai.image_prompts[-1] == "prompt-1 | cartoon"

    client.patch(url, json={"target": "image", "instruction": "blue"})
    assert ai.image_prompts[-1] == "prompt-1 | cartoon | blue"


def test_all_target_regenerates_everything(client, ai, card):
    data, url = card
    ai.image_bytes = JPEG
    body = client.patch(url, json={"target": "all"}).json()

    assert body["meaning"] != data["meaning"]
    assert body["example_target"] != data["example_target"]
    assert image_of(client, body) == JPEG


def test_failed_image_regeneration_keeps_card_and_old_image(client, ai, card):
    data, url = card
    ai.fail_images = True
    response = client.patch(url, json={"target": "image"})

    assert response.status_code == 502
    assert image_of(client, data) == PNG
    assert current(client).json()["cards"][0]["status"] == "COMPLETED"


def test_failed_text_regeneration_keeps_card(client, ai, card):
    data, url = card
    ai.fail_words = {"apple"}
    assert client.patch(url).status_code == 502

    restored = current(client).json()["cards"][0]
    assert restored["status"] == "COMPLETED"
    assert restored["example_target"] == data["example_target"]


def test_image_target_is_rejected_when_images_are_disabled(client, card, monkeypatch):
    _, url = card
    monkeypatch.setattr(settings, "GENERATE_IMAGES", False)
    assert client.patch(url, json={"target": "image"}).status_code == 409


def test_failed_card_is_regenerated_fully_whatever_the_target(client, ai):
    ai.fail_words = {"apple"}
    add_words(client, ["apple"])
    body = current(client).json()
    failed = body["cards"][0]
    assert failed["status"] == "FAILED"

    ai.fail_words = set()
    response = client.patch(card_url(body["batch_id"], failed["card_id"]), json={"target": "example"})

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "COMPLETED"
    assert result["meaning"] and result["has_image"]
    assert current(client).json()["status"] == "COMPLETED"


def test_pending_card_cannot_be_regenerated(client, db):
    batch_id, card_id = insert_pending_batch(db)
    assert client.patch(card_url(batch_id, card_id)).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"target": "nope"},
        {"meaning": "typed by the user"},  # manual editing is not supported
        {"instruction": "x" * 301},
    ],
)
def test_invalid_regenerate_requests(client, card, body):
    _, url = card
    assert client.patch(url, json=body).status_code == 422


def test_unknown_card_or_batch(client, card):
    data, url = card
    assert client.patch(card_url("missing", data["card_id"])).status_code == 404
    assert client.patch(url.replace(data["card_id"], "missing")).status_code == 404
