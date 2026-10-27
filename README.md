# Détecteur de risque financier

Alerte précoce sur les sociétés cotées américaines, construite uniquement à
partir de leurs dépôts publics (SEC EDGAR) et de leurs cours de bourse :
12 signaux financiers + un modèle d'apprentissage profond, fusionnés en un
niveau de risque par exercice (faible → modéré → élevé → critique), chaque
score remontant au dépôt exact qui l'a produit.

> **Avertissement** — outil informatif à vocation pédagogique. Il ne constitue
> ni un conseil en investissement, ni une recommandation d'achat ou de vente.
> Les scores sont des indicateurs de qualité d'information, pas des
> prévisions de faillite.

## Signaux

| Signal | Ce qu'il mesure | Seuil d'alerte |
|---|---|---|
| `altman` | Score Z d'Altman (solvabilité globale) | < 2,99 vigilance · < 1,81 défaillance |
| `piotroski` | Score F sur 9 critères de amélioration comptable | F < 3 défaillance · F < 7 vigilance |
| `beneish` | Score M de manipulation de résultats | M > −2,27 vigilance · M > −1,78 défaillance |
| `divergence` | Bénéfice net en hausse + cash-flow en baisse, 2 années de suite | streak ≥ 2 défaillance |
| `runway` | Trésorerie / brûlage mensuel de trésorerie | < 24 mois vigilance · < 12 mois défaillance |
| `late_filing` | Rapports annuels déposés en retard (NT 10-K/10-Q) | 1 NT vigilance · ≥ 2 défaillance |
| `critical_8k` | 8-K urgences : faillite (1.03), défaut (2.04), non-fiabilité (4.02)… | selon l'item, vigilance ou défaillance |
| `insider_sales` | Ventes de dirigeants ouvertes (Form 4) rapportées à la capitalisation | ≥ 0,25 % vigilance · ≥ 1 % défaillance |
| `net_debt_ebitda` | Dette nette / EBITDA | > 4× **et en hausse** défaillance |
| `dilution` | Croissance annuelle des actions en circulation | > 5 % vigilance · > 10 % défaillance |
| `composite` | Fusion pondérée des signaux disponibles | paliers 0,5 / 1,0 / 1,5 |
| `lstm` | Probabilité de détresse sur séries d'indicateurs (PyTorch) | affiché **à côté** du score classique |

Deux principes guident l'implémentation : **« donnée manquante » vaut mieux
qu'un faux score** (un signal non calculable est absent, jamais noté 0), et
**chaque score pointe son dépôt source** (`filings.url`).

## Résultats du backtest

Cohorte de **547 faillites** (premier 8-K « Item 1.03 » entre 2015 et 2025,
collecté par recherche EDGAR) contre **328 témoins sains** (S&P 500 jamais
concernés), toujours en ne regardant que l'information **disponible au moment
de l'alerte** :

| Règle d'alerte | Détection à 6 mois | à 12 mois | Faux positifs / an |
|---|---|---|---|
| Niveau **≥ modéré** (règle retenue) | **64,9 %** | **56,7 %** | **9,3 %** |
| Niveau ≥ modéré **+** une composante en défaillance | 63,8 % | 55,2 % | 8,5 % |

Cible de la feuille de route : 60–70 % de détection à 6 mois — atteinte.
Les poids des signaux ont été calibrés sur cette cohorte
(`scripts/tune_weights.py`), les métriques du modèle de deep learning sont
mesurées séparément (`scripts/train_lstm.py`) : sur ces données, les deux
approches se complètent, le classique garde la meilleure détection à 6 mois.

Le site publie ces résultats sur la page `/methodology`, avec des exemples de
faillites signalées à temps, signalées tard et manquées. Ses chiffres sont
figés dans `frontend/app/methodology/page.tsx` : les régénérer après tout
retune du composite.

## Architecture

- **Backend** — Python 3.14, FastAPI, PostgreSQL 17 (SQL brut via psycopg,
  pas d'ORM). Les routes publiques lisent les signaux précalculés chaque nuit
  (`app/jobs/nightly.py`) ; les routes privées de liste de suivi ne modifient
  que les données utilisateur et exigent une session Clerk vérifiée côté Next.
- **Frontend** — Next.js 16 (App Router, Tailwind v4, React 19), rendu côté
  serveur, sitemap + robots dynamiques pour l'indexation.
- **Données** — SEC EDGAR respecte la limite de 10 requêtes/s (User-Agent
  obligatoire, cache fichier), cours via l'API publique Yahoo Finance.
- **Deep learning** — LSTM PyTorch entraîné sur le même backtest, explicable
  par SHAP ; les signaux DL n'entrent **jamais** dans le composite, ils
  restent des informations à côté du score classique.

## Démarrage rapide

Prérequis : [Docker](https://docs.docker.com/), [uv](https://docs.astral.sh/uv/),
Node ≥ 20 avec pnpm (`corepack enable pnpm`).

```bash
# 1. Configuration — SEC_USER_AGENT exige un nom + e-mail réels (règle SEC)
cp .env.example .env          # PowerShell : Copy-Item .env.example .env

# 2. Base de données (PostgreSQL 17, port 5435)
docker compose up -d --wait

# 3. Dépendances Python
uv sync

# 4. Données de démonstration : le trio Apple / AMC / Bed Bath & Beyond
#    (~10 min, réseau : premier accès SEC + Yahoo, ensuite mis en cache)
uv run python -m scripts.fetch_phase0
uv run python -m scripts.fetch_prices
uv run python -m scripts.fetch_submissions
uv run python -m scripts.load_postgres
uv run python -m app.jobs.nightly --no-refresh

# 5. API + site
uv run uvicorn app.api.main:app --reload --port 8011 # → http://localhost:8011/health
pnpm --dir frontend install
pnpm --dir frontend dev                       # → http://localhost:3000
```

La recherche et les fiches publiques fonctionnent sans compte. Pour activer
les comptes et la liste de suivi en local, copier `frontend/.env.example` vers
`frontend/.env.local`, configurer les clés Clerk et partager la même valeur de
`WATCHLIST_API_SECRET` entre ce fichier et le `.env` racine.

Tests : `uv run pytest` (207 tests collectés).

Mise en production (GitHub Actions + Render + Vercel + Neon + Clerk) :
voir [docs/DEPLOY.md](docs/DEPLOY.md).

Pour charger la cohorte complète du backtest (875 entreprises, ~1 h, réseau) :

```bash
uv run python -m scripts.build_cohort
uv run python -m scripts.fetch_phase0   --manifest data/backtest/companies.json
uv run python -m scripts.fetch_prices   --manifest data/backtest/companies.json
uv run python -m scripts.fetch_submissions --manifest data/backtest/companies.json
uv run python -m scripts.load_postgres  --manifest data/backtest/companies.json
uv run python -m app.jobs.nightly       # ~1 h la première fois (cache EDGAR)
uv run python -m scripts.backtest       # rejoue les métriques ci-dessus
```

## Structure du dépôt

```
app/          API FastAPI + moteurs (normalize, signals, edgar, dl, ingest,
              backtest, jobs) — signaux purs et testables
scripts/      commandes batch : collecte SEC, ingestion, backtest, entraînement
tests/        suite pytest (207)
frontend/     application Next.js 16
data/         manifest de cohorte (versionné) + caches (gitignorés)
docker-compose.yml
```

## Contribuer et licence

Code sous licence [MIT](LICENSE) — voir [CONTRIBUTING.md](CONTRIBUTING.md) pour les conventions
(identifiants et commits en anglais, commentaires et textes en français).
