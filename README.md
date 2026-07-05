# Quolate

AI sourcing workbench for import-focused buyers. Runs 100% locally on Windows with zero running cost.

Two separate deployables with a clean HTTP API between them:

- `backend/` — Python 3.10+ / FastAPI / SQLAlchemy 2 / Alembic / Postgres + pgvector
- `frontend/` — Next.js 14 (App Router) / TypeScript / Tailwind / TanStack Query

Current status: the MVP is feature-complete end-to-end. **M0 (skeleton)**, **M1 (auth + projects + BOM)**, **M2 (ingestion pipeline)**, **M3 (comparison matrix + landed cost)**, **M4 (chat workbench with tools + web access)**, **M5 (tender intelligence: adapters, scraping, classification, correlation, notifications)** and **M6 (Next.js workbench + tenders UI, Playwright E2E, Vitest units)** are implemented and tested.

## Prerequisites (Windows)

1. **Ollama** for Windows, then pull models:
   ```powershell
   ollama pull bge-m3
   ollama pull qwen3:8b      # 8GB-VRAM machine (RTX 4070)
   # 4GB machine instead: ollama pull qwen3:4b  and set LLM_MODEL=qwen3:4b
   ```
   Ollama automatically offloads to CPU when VRAM is insufficient — no code change needed.
2. **Docker Desktop** (only used for Postgres). If Docker is unavailable, install native Postgres 16 and run `CREATE EXTENSION vector;` in the `quolate` database.
3. **Python 3.10+** and **Node 20+**.
4. **PaddleOCR** (only needed to process scanned/photo inputs; tests mock it):
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m pip install -e ".[ocr]"
   ```
5. **Tender scraping deps** (BeautifulSoup, trafilatura, ddgs, APScheduler, Playwright) are installed via the `scrape` extra, and the browser via Playwright:
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m pip install -e ".[scrape]"
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```
   The generic tender adapter only needs Chromium for JavaScript-rendered portals; the PPRA adapters and web-search chat tool work without it.

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Key values:

- The Postgres container is published on **host port 5433** (to avoid clashing with any native Postgres on 5432).
- On the 8GB machine keep `LLM_MODEL=qwen3:8b`; on the 4GB machine set `LLM_MODEL=qwen3:4b`.

Frontend: copy `frontend/.env.local.example` to `frontend/.env.local` (`NEXT_PUBLIC_API_URL=http://localhost:8000`).

## First-time setup

```powershell
# 1. Start Postgres (pgvector)
.\tasks.ps1 db

# 2. Backend deps
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ..

# 3. Apply migrations
.\tasks.ps1 migrate

# 4. (optional) seed a demo user + project
.\tasks.ps1 seed        # login: demo@quolate.local / demo12345

# 5. Frontend deps
cd frontend
npm install
cd ..
```

## Running

```powershell
.\tasks.ps1 dev     # backend on http://localhost:8000
.\tasks.ps1 web     # frontend on http://localhost:3000
```

Open http://localhost:3000, register, and create a project.

> Windows note: psycopg's async driver cannot run on uvicorn's default
> ProactorEventLoop. The backend is started via `backend/run.py`, which forces
> the `WindowsSelectorEventLoopPolicy`. This is a no-op on Linux/macOS.

## Testing

Backend fast suite (mock LLM + mock OCR, deterministic — covers M1–M5):

```powershell
.\tasks.ps1 test
# or: cd backend; .\.venv\Scripts\python.exe -m pytest -q
```

Additional backend suites (excluded by default):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -m llm        # live Ollama extraction
.\.venv\Scripts\python.exe -m pytest -m live       # live tender adapters against real portals
.\.venv\Scripts\python.exe -m pytest -m realdata   # runs over files in ../testdata
.\.venv\Scripts\python.exe -m pytest -m ocr        # requires a real PaddleOCR install
```

Drop real supplier docs into `testdata/` (gitignored) to exercise the `realdata` suite.

Frontend unit tests (Vitest) and end-to-end tests (Playwright):

```powershell
cd frontend
npm run test                       # Vitest units (TSV parser, matrix cell state, formatters)

# E2E needs the full stack running (backend on :8000, Postgres, Ollama):
npx playwright install chromium    # one-time
npm run e2e                        # starts the frontend automatically and runs the specs
```

The E2E specs cover the deterministic core flows (auth, project, BOM paste, matrix,
assumptions, XLSX export, document upload, tender source add + pull + saved filter).

## Feature overview (MVP)

- **Workbench** (`/projects/[id]`): streaming chat copilot on the left; `BOM | Inbox | Matrix` tabs on the right.
  - BOM: editable grid + paste-from-Excel; suppliers.
  - Inbox: drag-drop / paste-screenshot upload, per-document status, and a split-view review (page image + bounding-box overlay, confirm/edit with keyboard).
  - Matrix: server-computed landed cost, green/amber/red cell states, best-value highlight, click-through provenance, live assumptions (currency/duty/freight/LC), and XLSX export.
- **Tenders** (`/tenders`, `/tenders/sources`): add portal sources (PPRA federal/provincial adapters + a generic LLM adapter), pull on demand or on the daily schedule, filter, save filters (with a notification badge), and see "matches from your quotes".

## Cloud migration seams

Everything that changes for cloud is isolated behind four seams plus the jobs interface:

- Files: `app/storage/` (`StorageService`)
- Auth: `app/auth/deps.py` (`get_current_user`)
- LLM: `app/llm/client.py`
- Embeddings: `app/llm/embeddings.py`
- Jobs: `app/jobs/`

The frontend talks to the backend only via `NEXT_PUBLIC_API_URL`.
