import os
from contextlib import asynccontextmanager

from app.config import settings
from app.database import clean_old_data, engine, fail_interrupted_cards, init_db
from app.routes import flashcard
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session


@asynccontextmanager
async def lifespan(_: FastAPI):
    os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
    init_db()
    fail_interrupted_cards()
    with Session(engine) as session:
        clean_old_data(session)
    yield


app = FastAPI(
    title="Anki Local AI Flashcard Creation Server",
    description="Backend API integrating Qwen 9B and Stable Diffusion 1.5",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(flashcard.router)


@app.get("/health", tags=["Root"])
async def root():
    return {
        "status": "online",
        "message": "Anki Local AI Flashcard Server is running smoothly.",
        "text_model_configured": settings.TEXT_MODEL_NAME,
        "image_model_configured": settings.IMAGE_MODEL_NAME,
    }
