import os
import shutil
import tempfile

# Settings are read at import time, so configure the environment before importing the app
_tmp = tempfile.mkdtemp(prefix="anki-tests-")
os.environ.update(
    OUTPUT_DIR=os.path.join(_tmp, "exports"),
    DB_FILE=os.path.join(_tmp, "test.db"),
    GENERATE_IMAGES="true",
    RETENTION_HOURS="24",
    MAX_WORDS_PER_REQUEST="5",
    MAX_CARDS_PER_BATCH="6",
    MAX_UPLOAD_BYTES="1000",
)

import pytest  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.flashcard import AIFlashcard  # noqa: E402
from app.services.ai_service import AIGenerationError, ai_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from helpers import PNG  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402


class FakeAI:
    """Stands in for the local AI backend; each call gets a unique, traceable result."""

    def __init__(self):
        self.fail_words: set[str] = set()
        self.fail_images = False
        self.image_bytes = PNG
        self.calls = 0
        self.image_prompts: list[str] = []

    async def generate_flashcard(self, word, instruction=None, previous_example=None):
        self.calls += 1
        if word in self.fail_words:
            raise AIGenerationError("text model down")
        return AIFlashcard(
            ipa=f"/{word}/",
            meaning=f"meaning-{self.calls}",
            example_target=f"example-{self.calls} {instruction or ''}".strip(),
            example_meaning="example meaning",
            image_prompt=f"prompt-{self.calls}",
        )

    async def generate_image(self, image_prompt):
        self.image_prompts.append(image_prompt)
        if self.fail_images:
            raise AIGenerationError("image model down")
        return self.image_bytes

    async def refine_image_prompt(self, word, image_prompt, instruction):
        return f"{image_prompt} | {instruction}"


@pytest.fixture
def ai(monkeypatch) -> FakeAI:
    fake = FakeAI()
    for name in ("generate_flashcard", "generate_image", "refine_image_prompt"):
        monkeypatch.setattr(ai_service, name, getattr(fake, name))
    return fake


@pytest.fixture
def client(ai):
    SQLModel.metadata.drop_all(engine)
    shutil.rmtree(settings.OUTPUT_DIR, ignore_errors=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    with Session(engine) as session:
        yield session
