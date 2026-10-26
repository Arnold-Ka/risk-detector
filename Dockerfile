# Image Docker de l'API (Render), PostgreSQL externe (Neon).
# Les endpoints publics lisent les données ; les écritures sont limitées aux
# listes de suivi authentifiées par le BFF Next.js.
#
# torch et shap sont EXCLUS de l'installation : vérifié par grep, app/api/
# ne les importe jamais (l'inférence DL vit dans app/jobs/nightly.py, qui
# tourne dans GitHub Actions avec l'installation complète). Sans ce
# --no-install-package, l'image ferait ~2 Go pour l'API sans calcul ML.
FROM ghcr.io/astral-sh/uv:latest AS uv

FROM python:3.14-slim

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app

# UV_LINK_MODE=copy : interdit les liens durs (impossibles entre les
# couches Docker) ; bytecode compilé = démarrage uvicorn plus rapide.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# D'abord les dépendances seules : la couche reste valide tant que
# pyproject.toml/uv.lock ne changent pas (cache de build Docker).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-package torch --no-install-package shap

# Code application seulement (pas .venv local, pas data/, pas frontend/ :
# voir .dockerignore).
COPY app ./app

# $PORT est injecté par Render ; ne pas coder un port en dur.
CMD ["sh", "-c", "uv run --no-sync uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
