# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` is the canonical, maintained instruction file (working agreements, commands, invariants, data traps, deployment). It is imported below so there is a single source of truth — edit `AGENTS.md`, not this file, when rules change.

@AGENTS.md

## Code map (data flow)

The pipeline reads left to right; each stage lives in its own package under `app/`:

1. **Fetch** — `app/edgar/` (`client.py` = rate-limited, cached SEC client; `submissions.py`, `form4.py`; `yahoo.py` = prices/splits cache).
2. **Normalize** — `app/normalize/loader.py` + `xbrl_map.yaml` (tag → concept mapping) turn companyfacts into annual financials.
3. **Ingest** — `app/ingest/` writes ingestion tables (`companyfacts.py`, `form4.py`, `refresh.py`); `scripts/load_*` are batch wrappers over the same code.
4. **Signals** — `app/signals/` pure functions (Altman, Piotroski, Beneish, runway, leverage, dilution, divergence, events/8-K, insiders), wired by `compute.py`, aggregated by `composite.py`.
5. **DL** — `app/dl/` (`dataset.py`, `model.py`, `infer.py`, `attribution.py`) produces the separate `lstm` signal from `data/models/lstm.pt`; trained by `scripts/train_lstm.py`.
6. **Persist / orchestrate** — `app/jobs/nightly.py` (refresh → compute → replace signals per company); `app/db/repo.py` holds all SQL; schema in `app/db/schema.sql`.
7. **Serve** — `app/api/main.py` (public read-only routes) and `app/api/watchlist.py` (`/me/watchlist`, authenticated via the shared secret).
8. **Frontend** — `frontend/` Next.js app; `lib/api.ts` calls the FastAPI backend, `lib/server-watchlist.ts` + `app/api/` route handlers forward Clerk-verified watchlist calls server-side with `WATCHLIST_API_SECRET`; `proxy.ts` is the Next 16 request proxy (Clerk middleware, no-op when Clerk keys are absent).

Evaluation lives in `app/backtest/` (`cohort.py`, `metrics.py`) driven by `scripts/backtest.py` and `scripts/tune_weights.py`; README holds the baseline metrics any weight change must be compared against.

CI: `.github/workflows/nightly.yml` (scheduled nightly job) and `keepalive.yml` (pings the Render API `/health` every 14 min to avoid free-tier spin-down); neither runs tests, lint or build.
