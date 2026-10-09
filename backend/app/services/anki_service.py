import hashlib
import html
import os

import genanki
from app.config import settings
from app.models.flashcard import Card
from app.services import storage


class AnkiService:
    def __init__(self):
        self.card_style = """
        .card {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            font-size: 20px;
            text-align: center;
            color: #2c3e50;
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .word { font-size: 32px; font-weight: bold; color: #2980b9; margin-bottom: 5px; }
        .ipa { font-size: 18px; color: #7f8c8d; font-style: italic; margin-bottom: 20px; }
        .meaning { font-size: 24px; font-weight: bold; color: #27ae60; margin-top: 15px; }
        .example { font-size: 20px; color: #34495e; margin-top: 15px; font-style: italic; }
        .example-meaning { font-size: 16px; color: #95a5a6; margin-top: 5px; }
        .image-container img { max-width: 300px; max-height: 300px; border-radius: 8px; margin-top: 15px; }
        """

        front_html = """
        <div class="card">
            <div class="word">{{Word}}</div>
            <div class="ipa">{{IPA}}</div>
        </div>
        """

        back_html = """
        <div class="card">
            <div class="word">{{Word}}</div>
            <div class="ipa">{{IPA}}</div>
            <hr style="border: 0; border-top: 1px solid #ddd; margin: 20px 0;">
            <div class="meaning">{{Meaning}}</div>
            <div class="example">{{ExampleTarget}}</div>
            <div class="example-meaning">{{ExampleMeaning}}</div>
            <div class="image-container">{{Image}}</div>
        </div>
        """

        self.anki_model = genanki.Model(
            1607354829,
            "LocalAIFlashcardModel",
            fields=[
                {"name": "Word"},
                {"name": "IPA"},
                {"name": "Meaning"},
                {"name": "ExampleTarget"},
                {"name": "ExampleMeaning"},
                {"name": "Image"},
            ],
            templates=[{"name": "Card 1", "qfmt": front_html, "afmt": back_html}],
            css=self.card_style,
        )

    @staticmethod
    def _deck_id(batch_id: str) -> int:
        # Stable per batch so re-exporting updates the deck in Anki instead of duplicating it
        return (1 << 30) + int(hashlib.sha256(batch_id.encode()).hexdigest()[:8], 16) % (1 << 30)

    def create_apkg_package(self, batch_id: str, cards: list[Card]) -> str:
        os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

        deck = genanki.Deck(self._deck_id(batch_id), settings.EXPORT_DECK_NAME)
        media_files: list[str] = []

        for card in cards:
            image_field = ""
            path = storage.find_image(card.card_id) if card.has_image else None
            if path:
                media_files.append(path)
                image_field = f'<img src="{os.path.basename(path)}">'

            # Fields are rendered as HTML by Anki, so escape stored text
            deck.add_note(
                genanki.Note(
                    model=self.anki_model,
                    guid=genanki.guid_for(card.card_id),
                    fields=[
                        html.escape(card.word),
                        html.escape(card.ipa or ""),
                        html.escape(card.meaning or ""),
                        html.escape(card.example_target or ""),
                        html.escape(card.example_meaning or ""),
                        image_field,
                    ],
                )
            )

        package = genanki.Package(deck)
        package.media_files = media_files

        output_path = storage.export_path(batch_id)
        package.write_to_file(output_path)
        return output_path


anki_service = AnkiService()
