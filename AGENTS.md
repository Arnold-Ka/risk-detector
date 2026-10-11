# AGENTS.md

Pre-MVP personal project: an early-warning risk tool for US listed companies. The authoritative spec is `Feuille de route — Détecteur de risque financier.md` (French, includes phases, gates, and stack choices).

**Workflow convention:** the user implements, the agent reviews/explains — give exact commands and detailed reasoning (comments in code are wanted and welcome); don't implement features unless explicitly asked.

Git repo initialized, **first commit still pending**. No CI.

## Decisions locked (do not re-open these debates)

- Frontend: **Next.js + pnpm + Tailwind** (App Router, subfolder `frontend/`) — NOT HTMX, despite the roadmap offering both.
- Backend: Python FastAPI (`app/`) serving **JSON only**; Next.js renders all pages.
- **Open source: MIT license**, public GitHub repo planned (LICENSE file not created yet). Code is free (incl. commercial); monetization is the hosted service only.
- **Deep learning is in scope** (roadmap rev. Oct 2026): PyTorch — sequential model (LSTM/transformer) on normalized XBRL indicator series (trained on the backtest cohort, inference phase 2), plus a fine-tuned open-source transformer for report text (phase 3). DL signals sit *next to* classic scores, never replacing them unless they beat them on the backtest.
- Language: **code identifiers, comments, commits in English**; French for user-facing prose (roadmap, docs, UI text).
- Approach: full skeleton first (structure + stubs + schema), then fill phase by phase.
- Dev database: PostgreSQL 17 via Docker. **Port 5435** on the host (5432 is taken by another local container `fa_pg_sql`) — `DATABASE_URL` must say `localhost:5435`.

## Environment

- Windows + PowerShell. Venv at `.venv/` (uv 0.11.7), Python **3.14.3**; manifest `pyproject.toml` + `uv.lock` — install with `uv add <pkg>`, run with `uv run …`.
- Backend deps installed: fastapi, uvicorn, psycopg[binary], pydantic-settings, httpx, pyyaml, pytest, requests. **`pandas` NOT installed yet** (roadmap assumes it, add when the normalizer lands). `tensorflow` (2.22.0-rc0, for the notebook) prints oneDNN/absl warnings on import — harmless.
- **pnpm 12.10.1** (via corepack), **Docker 29.5**, Node 24. No native PostgreSQL — use Docker only.
- `.env` exists (gitignored) — pydantic-settings loads it at import time; **`from app.config import settings` crashes if `.env` is missing**. `SEC_USER_AGENT` must be a real name+email before any SEC request.
- `calculate_risk.ipynb` kernel is `.venv (3.14.3)`; keep it that way.
- Roadmap filename has French accents + an em dash; PowerShell output/globs mangle it — use literal paths / `[System.IO.Directory]::GetFiles`.

## Commands

| Action | Command |
|---|---|
| DB up (waits for healthy) | `docker compose up -d --wait` |
| DB reset + replay schema | `docker compose down -v` then `up -d --wait` |
| Inspect schema | `docker compose exec db psql -U risk -d risks -c "\dt"` (7 tables) |
| Run API | `uv run uvicorn app.api.main:app --reload` → `GET /health` |
| Smoke API w/o server | `uv run python -c "from fastapi.testclient import TestClient; from app.api.main import app; print(TestClient(app).get('/health').json())"` |
| Nightly job (stub) | `uv run python -m app.jobs.nightly` — always `-m`, else `app.*` imports fail |
| Tests | `uv run pytest` — **`tests/` does not exist yet** → collects 0, exit code 5 (not a failure of the code) |

## Current state — do not mistake for working code

- Implemented (stubs): `app/api/main.py` (`/health` works, `/companies/{cik}` returns 501), `app/config.py`, `app/db/repo.py`, `app/edgar/client.py` (rate-limit + User-Agent only, no cache yet), `app/signals/altman.py` (**always returns None** — formula TODO), `app/jobs/nightly.py` (prints a TODO), `app/jobs/poll_8k.py` (docstring only).
- Missing: `frontend/`, `tests/`, `app/signals/` (piotroski/beneish/divergence/runway/composite), real EDGAR download, `app/db/` `__init__` files exist but no repository functions beyond `get_conn()`.
- `app/db/schema.sql` is **live** (7 tables applied by docker-entrypoint-initdb.d). Editing it requires `docker compose down -v` to replay.
- `main.py` (root) is an empty leftover; `data.sqlite` is a 0-byte scratch file — planned DB is **PostgreSQL, not SQLite**.
- `data-script.sql` is an invalid historical draft (wrong DROP DATABASE syntax, `gen_ramdom_uuid` typo). Superseded by `app/db/schema.sql`; never execute it.

## Spec facts that constrain implementation

- SEC EDGAR: max 10 requests/second (client enforces `MIN_INTERVAL = 0.1`), `User-Agent` must include name+email, cache responses instead of re-querying per user request.
- MVP signals: Altman Z (< 1.81 = distress), Piotroski F (0–2 = weak), Beneish M (> -1.78 = suspect), earnings/cash divergence, cash runway (< 12 months). Net-debt/EBITDA and share dilution are V2. Deep-learning signals (phase 2+): probability of distress from indicator sequences, with per-variable attribution (SHAP).
- Scores unreliable for banks, insurers, REITs — filter on `companies.sector_group`.
- Product rules: show "donnée manquante" rather than a wrong score (signal functions return `None` on missing data); every score traces to the exact source filing (`signals.filing_id` → `filings.url`); precompute nightly, API only reads.
- Roadmap gate: Phase 0 (3 companies, Z-score computed by hand) precedes building the real EDGAR pipeline.

## Style

Code identifiers/comments/commits: English. Prose and user-facing text: French. Match the language of the file you are editing. Detailed explanatory comments in code are explicitly wanted.
