import os

from app.config import settings


IMAGE_EXTENSIONS = ("png", "jpg", "webp")


def detect_image_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _image_file(card_id: str, ext: str) -> str:
    return os.path.join(settings.OUTPUT_DIR, f"cache_{card_id}.{ext}")


def find_image(card_id: str) -> str | None:
    for ext in IMAGE_EXTENSIONS:
        path = _image_file(card_id, ext)
        if os.path.exists(path):
            return path
    return None


def export_path(batch_id: str) -> str:
    return os.path.join(settings.OUTPUT_DIR, f"{batch_id}.apkg")


def remove_image(card_id: str) -> None:
    for ext in IMAGE_EXTENSIONS:
        remove_file(_image_file(card_id, ext))


def save_image(card_id: str, data: bytes) -> None:
    ext = detect_image_extension(data)
    if ext is None:
        raise ValueError("Unsupported image data")
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    remove_image(card_id)  # a regenerated image may have a different format
    with open(_image_file(card_id, ext), "wb") as f:
        f.write(data)


def remove_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
