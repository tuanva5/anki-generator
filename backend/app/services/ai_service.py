import base64
import json
import logging
import re

import httpx
from app.config import settings
from app.schemas.flashcard import MAX_FIELD_LENGTH, AIFlashcard
from app.services import storage
from pydantic import ValidationError

logger = logging.getLogger(__name__)

TEXT_ATTEMPTS = 2


class AIGenerationError(Exception):
    """Raised when the local AI backend fails or returns unusable output."""


class AIService:
    def __init__(self):
        self.base_url = settings.LOCALAI_BASE_URL

    def _text_payload(self, word: str, instruction: str | None, previous_example: str | None) -> dict:
        system_prompt = (
            "You are an expert lexicographer and Anki flashcard creator. Analyze the vocabulary "
            "word provided by the user and return a structured analysis in strict JSON format.\n"
            "Output ONLY a valid JSON object with the keys below: no preamble, no markdown code "
            "blocks, no closing remarks.\n\n"
            "Expected JSON Structure:\n"
            "{\n"
            '  "ipa": "The standard International Phonetic Alphabet pronunciation",\n'
            f'  "meaning": "The concise meaning or translation in {settings.TARGET_LANGUAGE}",\n'
            '  "example_target": "A natural, contextual English example sentence using the word",\n'
            f'  "example_meaning": "The {settings.TARGET_LANGUAGE} translation of the example sentence",\n'
            '  "image_prompt": "A simple, concrete English text-to-image prompt representing the word '
            "visually (e.g., 'a fresh red apple on a wooden table, high quality photo')\"\n"
            "}"
        )
        user_prompt = f"Analyze the word: {word}"
        if previous_example:
            user_prompt += f"\nWrite a different example sentence than this one: {previous_example}"
        if instruction:
            user_prompt += f"\nAdditional instruction for the example sentence: {instruction}"
        return {
            "model": settings.TEXT_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }

    @staticmethod
    def _strip_thinking(content: str) -> str:
        # Reasoning models may prepend <think> blocks
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    @classmethod
    def _parse_card_json(cls, content: str) -> AIFlashcard:
        content = cls._strip_thinking(content)
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object found in model output")
        return AIFlashcard.model_validate(json.loads(content[start : end + 1]))

    async def _chat(self, client: httpx.AsyncClient, payload: dict) -> str:
        response = await client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def generate_flashcard(
        self, word: str, instruction: str | None = None, previous_example: str | None = None
    ) -> AIFlashcard:
        payload = self._text_payload(word, instruction, previous_example)
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(1, TEXT_ATTEMPTS + 1):
                try:
                    return self._parse_card_json(await self._chat(client, payload))
                except httpx.HTTPError as e:
                    raise AIGenerationError(f"Text model request failed: {e}") from e
                except (ValueError, KeyError, IndexError, TypeError, ValidationError) as e:
                    # json.JSONDecodeError and pydantic's ValidationError are ValueErrors
                    last_error = e
                    logger.warning("Invalid model output for %r (attempt %d): %s", word, attempt, e)

        raise AIGenerationError(f"Text model returned invalid output: {last_error}")

    async def refine_image_prompt(self, word: str, image_prompt: str, instruction: str) -> str:
        payload = {
            "model": settings.TEXT_MODEL_NAME,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You rewrite text-to-image prompts. Apply the requested change to the current prompt "
                        "and output ONLY the new English prompt on a single line, with no quotes or commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Word: {word}\nCurrent prompt: {image_prompt}\nRequested change: {instruction}",
                },
            ],
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                content = await self._chat(client, payload)
            except httpx.HTTPError as e:
                raise AIGenerationError(f"Text model request failed: {e}") from e
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise AIGenerationError(f"Text model returned invalid output: {e}") from e

        prompt = " ".join(self._strip_thinking(content).split()).strip("\"'")
        if not prompt or len(prompt) > MAX_FIELD_LENGTH:
            raise AIGenerationError("Text model returned an unusable image prompt")
        return prompt

    async def generate_image(self, image_prompt: str) -> bytes:
        data = await self._fetch_image(image_prompt)
        if storage.detect_image_extension(data) is None:
            raise AIGenerationError("Image model returned data that is not a PNG, JPEG or WebP image")
        return data

    async def _fetch_image(self, image_prompt: str) -> bytes:
        payload = {
            "model": settings.IMAGE_MODEL_NAME,
            "prompt": image_prompt,
            "size": "512x512",
            "n": 1,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                response = await client.post(f"{self.base_url}/images/generations", json=payload)
                response.raise_for_status()
                item = (response.json().get("data") or [{}])[0]
                if item.get("b64_json"):
                    return base64.b64decode(item["b64_json"])
                if item.get("url"):
                    image_response = await client.get(item["url"])
                    image_response.raise_for_status()
                    return image_response.content
            except (httpx.HTTPError, ValueError) as e:
                raise AIGenerationError(f"Image model request failed: {e}") from e
        raise AIGenerationError("Image model returned no image data")


ai_service = AIService()
