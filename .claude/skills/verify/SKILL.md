---
name: verify
description: Build, launch, and drive Quolate to verify a change end-to-end (FastAPI backend + Next.js frontend + Ollama).
---

# Verifying Quolate changes

## Launch the stack

```powershell
docker compose -f docker-compose.yml up -d db     # Postgres :5433 (needs Docker Desktop running)
cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head
cd backend; .\.venv\Scripts\python.exe run.py      # backend :8000 (MUST use run.py, not bare uvicorn — Windows event loop)
cd frontend; npm run dev                           # frontend :3000 (Playwright webServer auto-starts it too)
```

- Health: `GET :8000/health`; LLM: `GET :8000/status/llm` (Ollama on :11434 — `ollama list` wakes the service if it's down).
- Configured model comes from `.env` `LLM_MODEL`; LLM calls take ~10–20 s each on CPU.

## Drive the surfaces

- **API**: register/login via `POST /auth/register` + `/auth/login` (JSON email/password), then Bearer token. Docs at `:8000/docs`.
- **GUI**: Playwright is set up (`frontend/e2e`, `npx playwright test e2e/<spec>.ts`). `e2e/helpers.ts::authInit` registers a user and injects the JWT into localStorage — no manual login page driving needed. The Playwright config auto-starts `npm run dev` and reuses a running one.
- Reference spec: `e2e/duty-verify.spec.ts` (paste invoice → LLM parse → per-item HS classify → calculate → screenshots; screenshots go to `VERIFY_SHOTS_DIR`).

## Gotchas

- Backend 500s on DB ops usually mean it was started without `run.py` (Proactor loop breaks psycopg async on Windows).
- `pytest` uses a separate `quolate_test` DB and the mock LLM (`LLM_BASE_URL=mock`) — passing tests are CI evidence, not runtime verification.
- Duty calculator: known duty rates come from `duty_tax_rates` (seed via `.\tasks.ps1 seed-duty`, demo figures only) and per-user `hs_rate_memory`; prefill mixes these with sheet defaults, so rate values in the UI depend on DB state.
