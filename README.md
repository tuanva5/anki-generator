# Anki Local AI Flashcard Creation Server

An automated, self-hosted platform built with a **FastAPI backend** and a **Vue 3 frontend** that leverages local LLMs and Diffusion models to streamline flashcard generation. This application runs completely offline on **Apple Silicon (M4, 32GB Unified Memory)** and packages flashcards using **`genanki`** to ensure full database isolation and zero runtime conflicts.

---

## 🚀 Project Roadmap

### Phase 1: Core Generation & Review Web UI (Current Phase)
- **Local AI Orchestration:** Process text queries through **Qwen 2.5/3.5 (9B)** for structured linguistic data, and generate visual cues via **Stable Diffusion 1.5 GGML**.
- **Genanki Package Compiler:** Server uses `genanki` to pack fields, HTML/CSS layouts, and multimedia assets directly into self-contained `.apkg` files without needing Anki Desktop open or risking database lockups.
- **Vue 3 Review Dashboard:** A separate modern SPA dashboard to preview cards before compiling them. Features interactive actions to **manually edit fields**, **manually trigger image/text regeneration**, or **prompt the AI to refine contents** with custom instructions via a chat button. Once approved, download or trigger the local package export.

### Phase 2: Input Ecosystem & Integrations (Future)
- **Browser Extension:** A dedicated client extension to highlight text on any web page (e.g., reading news, Dokkai parsing) and send it directly to the server's creation pipeline.
- **Mobile Integration:** Enable reading apps or mobile endpoints to directly request and ingest generated `.apkg` files seamlessly over a local area network (LAN).

---

## 🛠️ Hardware & AI Stack Setup
The pipeline is optimized for **Apple M4 with 32GB Unified Memory**, balancing high intelligence and instant image feedback completely local:

- **Text Pipeline:** `Qwen 3.5 (9B)` via LocalAI (Quantization: `Q8_0`). The request need to support text generation for all content types so an [uncensored version](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF) is recommended.
- **Image Pipeline:** `Stable Diffusion 1.5 GGML` via LocalAI. Generates 512x512 resolution images in <1s. Memory footprint: ~1.5GB. NSFW content is inapprotiate and dangerous for learning purposes, need to test if it could work well witch the text pipeline.
- **Total AI RAM Allocation:** ~8GB - 10GB (Leaving plenty of headroom for macOS and web tasks).

---

## 📁 Project Structure

```text
anki-generator-server/
├── backend/                # FastAPI Application
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py         # Server entrypoint & FastAPI initialization
│   │   ├── config.py       # Environment variable parsing & settings
│   │   ├── schemas/        # Pydantic schemas for data validation
│   │   │   └── card.py
│   │   ├── services/       # Business logic layer
│   │   │   ├── ai_service.py   # LocalAI client (Qwen JSON & SD image)
│   │   │   └── anki_service.py # Card package builder using genanki
│   │   └── routes/         # REST API endpoints
│   │       └── generator.py# Creation, review, and regeneration routes
│   ├── exports/            # Local directory where generated .apkg files are saved
│   ├── .env.example        # Template for backend environment variables
│   └── requirements.txt    # Python package dependencies
│
├── frontend/               # Vue 3 Single Page Application (Vite)
│   ├── src/
│   │   ├── assets/
│   │   ├── components/     # Reusable components (Card Editor, AI Chat Panel)
│   │   ├── views/          # Main Dashboard pages
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json        # Frontend Node.js dependencies
│   └── vite.config.js      # Vite configuration (includes API dev proxy config)
│
└── README.md
```

---

## ⚙️ Prerequisites & Setup

### 1. Configure LocalAI
Ensure your LocalAI application is active on your machine and has the following model mappings configured in your local models path:
- A text model alias named `qwen` matching your 9B model.
- An image model alias named `stable-diffusion` matching your 1.5 GGML file.

### 2. Backend Installation (FastAPI)
Navigate to the backend directory, spin up the Python environment, and start the API:

```bash
cd backend

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Create your .env file
cp .env.example .env

# Start your backend server
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Installation (Vue 3 + Vite)
Open a **separate terminal**, navigate to the frontend directory, install Node modules, and run the hot-reloading development server:

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite development server
npm run dev
```
*The web interface will typically be available at `http://localhost:5173`.*

---

## 📊 Flashcard Architecture (HTML Structure)
Every flashcard created is stored in Anki across discrete semantic atomic fields rather than a lumped text field. This allows global template re-styling anytime: (* The below content could be changed later)

- **Front/Word:** The target phrase or vocabulary.
- **IPA:** Phonetics / Pronunciation notation.
- **Meaning:** Native translation or plain target language definition.
- **Context/Example:** The generated target sentence.
- **Audio:** `[sound:xxx.mp3]` reference syntax generated or requested.
- **Image:** `<img src="xxx.jpg">` rendered within the target card deck layout.
