import asyncio

import pytest
from app.services.ai_service import AIGenerationError, AIService
from helpers import PNG

CARD_JSON = (
    '{"ipa": "/a/", "meaning": "m", "example_target": "e", '
    '"example_meaning": "em", "image_prompt": "p", "extra": "ignored"}'
)


@pytest.mark.parametrize(
    "content",
    [
        CARD_JSON,
        f"```json\n{CARD_JSON}\n```",
        f"<think>reasoning {{with braces}}</think>\n{CARD_JSON}",
        f"Here you go: {CARD_JSON} Hope it helps!",
    ],
)
def test_parse_card_json_tolerates_wrapping(content):
    card = AIService._parse_card_json(content)
    assert (card.ipa, card.meaning, card.image_prompt) == ("/a/", "m", "p")


@pytest.mark.parametrize("content", ["no json here", "{not json}", '{"ipa": "/a/"}', '{"ipa": "", "meaning": "m"}'])
def test_parse_card_json_rejects_bad_output(content):
    with pytest.raises(ValueError):
        AIService._parse_card_json(content)


def test_generate_image_rejects_non_image_data(monkeypatch):
    service = AIService()

    async def fetch(_prompt):
        return b"<html>error page</html>"

    monkeypatch.setattr(service, "_fetch_image", fetch)
    with pytest.raises(AIGenerationError):
        asyncio.run(service.generate_image("a prompt"))


def test_generate_image_accepts_real_formats(monkeypatch):
    service = AIService()

    async def fetch(_prompt):
        return PNG

    monkeypatch.setattr(service, "_fetch_image", fetch)
    assert asyncio.run(service.generate_image("a prompt")) == PNG
