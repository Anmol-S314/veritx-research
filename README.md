# Meeting Intelligence System

Real-time meeting assistant that listens to conversations, answers questions from past meeting transcripts, and suggests proactive questions — all running locally.

## Quick Start

```bash
cd qwen_meet
bash setup.sh        # creates .venv (CPU-only), installs deps, makes .env + default project
# edit .env -> add your QWEN_API_KEY / GROQ_API_KEY
./run.sh             # starts the server on http://localhost:8001
```

CPU-only — no GPU or CUDA required. First run downloads two small models
(MiniLM embedder + tiny.en Whisper) to your Hugging Face cache.

Open http://localhost:8001

## Features

- **Live transcription** — captures mic + system audio, transcribes with Whisper
- **Auto-answer** — detects questions and answers from past transcripts
- **Proactive suggestions** — suggests 3 relevant questions, updates every 18s
- **Project memory (digest)** — per-project summary of decisions, action items, open questions & entities; grounds every answer
- **Self-learning** — 👍 / 👎 (with optional correction) teaches the assistant; validated answers are reused on similar questions
- **Cross-encoder reranking** — sharper retrieval over the FAISS shortlist
- **Multi-project** — organize transcripts by project/client
- **File editor** — edit transcript files directly in the browser
- **Contradiction detection** — flags conflicts with past meetings
- **LLM-powered answers** — Qwen for deep thinking, Groq for speed
- **Click-to-answer** — click any transcript line to get an AI answer
- **Ask anything** — floating chat box for project questions

## Configuration

Secrets live in `.env` (never committed). Copy `.env.example` and fill in:

```
QWEN_API_KEY=...      QWEN_BASE_URL=http://your-qwen-host:8000/v1   QWEN_MODEL=qwen3.6-27b
GROQ_API_KEY=...      GOOGLE_API_KEY=...   (optional)
```

The app works without keys too — it falls back to local retrieval-only answers.

Prefer a UI? Click the **terminal icon** in the header to open the **Setup
console** — test your mic & speakers (live level bars) and enter/update API keys
right in the browser (written to `.env`, applied live, no restart). Headless? the
same audio check is on the CLI: `make audio` (or `python -m mis.audio_check --test`).

## Architecture

```
Frontend (HTML/JS) ←→ FastAPI Server ←→ FAISS + MiniLM
                         ↕
                   Project Manager
                   (multi-project CRUD)
                   STT (faster-whisper + PyAudio)
```

## Audio Capture

The system captures both:
- **Your microphone** — what you say
- **System audio** — other participants' voices (via loopback)

This works for Google Meet, Zoom, Teams, and any other meeting app.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard |
| `POST /api/query` | Ask a question |
| `GET /api/project/digest` | Project memory (summary, decisions, action items, entities) |
| `POST /api/feedback` | 👍/👎 + correction → feeds self-learning |
| `GET /api/self-learning` | Feedback + learned-answer stats |
| `GET /api/suggestions` | Get proactive questions |
| `GET /api/projects` | List projects |
| `POST /api/projects/create` | Create project |
| `POST /api/projects/upload` | Upload transcript |
| `GET /api/projects/files` | List project files |
| `GET /api/projects/file/read` | Read file content |
| `POST /api/projects/file/save` | Save edited file |
| `GET /api/audio-devices` | List audio devices |
| `GET /api/audio-test` | Test audio capture |
| `GET /api/health` | Server health check |
| `WS /ws/transcript` | Live transcription stream |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Embeddings | all-MiniLM-L6-v2 (384-dim) |
| Vector search | FAISS binary + int8 rescore + BM25 |
| LLM | Qwen 3.6 27B (deep thinking), Groq Llama 8B (fast) |
| STT | faster-whisper (tiny.en) |
| Audio | PyAudio (mic + loopback mix) |
| Server | FastAPI + uvicorn |
| Frontend | Vanilla HTML/JS/CSS |

## Deploy

### One command
```bash
bash run.sh
```

### Docker
```bash
docker build -t meeting-intel .
docker run -p 8001:8001 -v $(pwd)/projects:/app/projects meeting-intel
```

## Tests

End-to-end suite covering every feature (incl. a simulated meeting over the
WebSocket, the self-learning loop, digest memory, and path-traversal guards):

```bash
pip install pytest
python -m pytest tests/ -q
```

## Spec

Full specification in `SPEC.md` — architecture, edge cases, task breakdown.
Design document in `DESIGN_DOC.md` — colors, typography, components.
