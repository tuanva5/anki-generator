import os

import pytest
from app.config import settings
from app.services import storage
from helpers import JPEG, PNG


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, "png"),
        (JPEG, "jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"GIF89a", None),
        (b"", None),
    ],
)
def test_detect_image_extension(data, expected):
    assert storage.detect_image_extension(data) == expected


def test_save_image_replaces_a_previous_format(client):
    storage.save_image("card1", PNG)
    assert storage.find_image("card1").endswith("cache_card1.png")

    storage.save_image("card1", JPEG)
    assert storage.find_image("card1").endswith("cache_card1.jpg")
    assert not os.path.exists(os.path.join(settings.OUTPUT_DIR, "cache_card1.png"))

    storage.remove_image("card1")
    assert storage.find_image("card1") is None


def test_save_image_rejects_non_images(client):
    with pytest.raises(ValueError):
        storage.save_image("card2", b"<html>not an image</html>")
    assert storage.find_image("card2") is None
