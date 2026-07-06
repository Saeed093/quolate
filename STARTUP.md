# Quolate Startup Guide

Step-by-step instructions for starting the backend and frontend on a fresh Windows machine or after a reboot.

---

## Prerequisites checklist

Before starting, make sure the following are installed and available on your system:

| Tool             | Purpose                              | Verify with                    |
|------------------|--------------------------------------|--------------------------------|
| Docker Desktop   | Runs the Postgres + pgvector database | `docker --version`            |
| Python 3.10+     | Backend runtime                      | `python --version`            |
| Node 20+         | Frontend runtime                     | `node --version`              |
| Ollama           | Local LLM inference                  | `ollama --version`            |

---

## Copy-paste commands (exact terminal lines)

You need **3 terminals** open. Run these in order.

### Terminal 1 — Docker (database) + Ollama

Make sure Docker Desktop is running, then:

```powershell
docker compose -f e:\mtech\quolate\application\quolate\docker-compose.yml up -d db
```

Ollama should already be running in the background (it starts with Windows). Verify your models are pulled:

```powershell
ollama list
```

If `qwen3:8b` or `bge-m3` are missing, pull them:

```powershell
ollama pull qwen3:8b
ollama pull bge-m3
```

**First time only** — install backend extras (OCR for scanned PDFs, scraping for tender pulls):

```powershell
cd e:\mtech\quolate\application\quolate\backend
.\.venv\Scripts\pip install ".[ocr,scrape]"
```

**First time only** — apply database migrations:

```powershell
cd e:\mtech\quolate\application\quolate\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### Terminal 2 — Backend

```powershell
cd e:\mtech\quolate\application\quolate\backend
.\.venv\Scripts\python.exe run.py
```

Backend starts on http://localhost:8000. Keep this terminal open.

Verify in a browser: http://localhost:8000/health should show `{"status":"ok"}`.

API docs: http://localhost:8000/docs

### Terminal 3 — Frontend

```powershell
cd e:\mtech\quolate\application\quolate\frontend
npm run dev
```

Frontend starts on http://localhost:3000. Keep this terminal open.

Open http://localhost:3000 in your browser. You'll see the login page.

---

## Quick-reference table

| Terminal | Command | What it starts | URL |
|----------|---------|----------------|-----|
| 1 | `docker compose -f ...\docker-compose.yml up -d db` | Postgres + pgvector | `localhost:5433` (DB) |
| 1 | `ollama list` (verify) | Ollama LLM (runs in background) | `localhost:11434` |
| 2 | `cd backend` then `.\.venv\Scripts\python.exe run.py` | FastAPI backend | http://localhost:8000 |
| 3 | `cd frontend` then `npm run dev` | Next.js frontend | http://localhost:3000 |

---

## Environment files

| File                           | Purpose                                        |
|--------------------------------|------------------------------------------------|
| `quolate/.env`                 | Backend config (DB URL, JWT secret, LLM, etc.) |
| `quolate/frontend/.env.local`  | Frontend config (`NEXT_PUBLIC_API_URL`)         |

Create these from the provided examples if they don't exist:

```powershell
# From the quolate/ root:
Copy-Item .env.example .env
Copy-Item frontend\.env.local.example frontend\.env.local
```

Key settings to review in `.env`:

```
DATABASE_URL=postgresql+psycopg://quolate:quolate@localhost:5433/quolate
LLM_MODEL=qwen3:8b          # use qwen3:4b on the 4GB-VRAM machine
ALLOW_ORIGINS=http://localhost:3000
```

---

## Stopping everything

```powershell
# Frontend: Ctrl+C in terminal 3
# Backend:  Ctrl+C in terminal 2
# Database:
docker compose -f docker-compose.yml down       # stops container, keeps data
docker compose -f docker-compose.yml down -v     # stops container AND deletes data
```

---

## Troubleshooting

### Backend returns 500 on database operations

The most likely cause on Windows is the event loop. The backend **must** be started via `run.py` (or `.\tasks.ps1 dev`), not via a bare `uvicorn app.main:app` command, because `run.py` forces the `WindowsSelectorEventLoopPolicy` before uvicorn starts.

### Database connection refused

- Check Docker Desktop is running: `docker info`
- Check the container is healthy: `docker inspect --format "{{.State.Health.Status}}" quolate_db`
- Make sure nothing else is using port 5433: `Get-NetTCPConnection -LocalPort 5433`
- If using native Postgres instead of Docker, update `DATABASE_URL` in `.env` to point to your instance and ensure the `vector` extension is installed: `CREATE EXTENSION IF NOT EXISTS vector;`

### Frontend can't reach the backend

- Verify `NEXT_PUBLIC_API_URL` in `frontend/.env.local` is set to `http://localhost:8000`
- Verify the backend is running and returns `{"status":"ok"}` at `/health`
- Check that `ALLOW_ORIGINS` in `.env` includes `http://localhost:3000`

### Ollama models not found

```powershell
ollama list                          # see what's pulled
ollama pull qwen3:8b                 # LLM
ollama pull bge-m3                   # embeddings
```

The backend will still start without Ollama, but document ingestion and embedding calls will fail at runtime. Tests use `LLM_BASE_URL=mock` and don't need Ollama.

### `No module named 'paddleocr'` during tender indexing

OCR is an optional dependency. Install it once:

```powershell
cd e:\mtech\quolate\application\quolate\backend
.\.venv\Scripts\pip install ".[ocr]"
```

Restart the backend after installing. Text-based PDFs work without OCR; scanned PDF attachments need PaddleOCR.
