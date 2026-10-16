"""Application FastAPI — la couche HTTP du backend.

Périmètre (feuille de route §4) : API JSON uniquement. Les pages sont
rendues par le frontend Next.js (`frontend/`), qui appelle ces endpoints.
Le backend ne rend jamais de HTML lui-même.

Règles respectées ici :
  - l'API ne CALCULE rien : elle lit les signaux pré-calculés par le job
    nocturne (app/jobs/nightly.py) — « pré-calculer plutôt que calculer à
    la demande » (§4) ;
  - réponse 404 sur CIK inconnu (pas d'objet vide qui ressemblerait à une
    entreprise sans risque).
"""

from fastapi import FastAPI, HTTPException, Query

from app.db.repo import (
    get_company,
    get_conn,
    latest_signals,
    list_companies,
    search_companies,
    signal_history,
)

# `title` apparaît dans la documentation auto-générée (/docs et /redoc) —
# utile pour tester les endpoints à la main tant que le frontend n'existe pas.
app = FastAPI(title="Risk Detector API")


@app.get("/health")
def health():
    """Sonde de vivacité (liveness).

    Utilisée par les vérifications de type docker --wait, par le frontend et
    par nous-mêmes pour répondre « l'API est-elle levée ? » sans toucher à la
    base de données. Délibérément SANS requête Postgres : santé = le processus
    répond, la disponibilité de la DB se vérifie ailleurs (docker compose ps
    du service db).
    """
    return {"status": "ok"}


@app.get("/search")
def search(q: str = Query(min_length=1, max_length=100)):
    """Recherche d'entreprise par nom, symbole boursier ou CIK.

    Feuille de route §9 (site minimal) : « recherche par nom ou symbole ».
    Retourne une liste (possibly vide) — jamais d'erreur pour « pas de
    résultat », c'est une réponse légitime. Le niveau composite éventuel
    est inclus pour afficher le risque dans les suggestions.
    """
    query = q.strip()
    if not query:
        return []  # que des espaces : pas de résultat, pas d'erreur
    conn = get_conn()
    try:
        return search_companies(conn, query)
    finally:
        conn.close()


@app.get("/companies")
def list_companies_endpoint():
    """Liste de toutes les entreprises suivies (identité seule, pas de signaux).

    Sert le sitemap du frontend (feuille de route §7 : « pages publiques par
    entreprise, indexables par Google ») — chaque fiche /company/{cik} doit
    apparaître dans sitemap.xml, ce qui exige d'énumérer les CIK sans passer
    par la recherche (qui exige une requête `q`). Léger volontairement :
    ~875 lignes d'identité ; l'identifiant public est le CIK (pas l'uuid
    interne de la table companies, qui n'est pas exposé par l'API).

    Note : enregistré avant /companies/{cik} pour la lisibilité — FastAPI
    distingue les routes par structure de chemin, pas par ordre.
    """
    conn = get_conn()
    try:
        return [
            {
                "cik": row["cik"],
                "name": row["name"],
                "ticker": row["ticker"],
                "sector_group": row["sector_group"],
            }
            for row in list_companies(conn)
        ]
    finally:
        conn.close()


@app.get("/companies/{cik}")
def get_company_card(cik: int):
    """Fiche de risque d'une entreprise, identifiée par son CIK SEC.

    Retourne l'identité + le dernier signal de chaque type (la lecture
    « aujourd'hui » de la fiche). L'historique complet est sur
    /companies/{cik}/signals.

    Note : un `def` simple (pas `async def`) suffit — FastAPI exécute les
    endpoints synchrones dans une threadpool et psycopg est bloquant.
    """
    conn = get_conn()
    try:
        company = get_company(conn, cik)
        if company is None:
            raise HTTPException(status_code=404, detail=f"CIK {cik} inconnu")
        return {**company, "signals": latest_signals(conn, company["id"])}
    finally:
        conn.close()


@app.get("/companies/{cik}/signals")
def get_company_signals(cik: int):
    """Historique complet des signaux (graphiques d'évolution, backtest)."""
    conn = get_conn()
    try:
        company = get_company(conn, cik)
        if company is None:
            raise HTTPException(status_code=404, detail=f"CIK {cik} inconnu")
        return {"cik": cik, "signals": signal_history(conn, company["id"])}
    finally:
        conn.close()
