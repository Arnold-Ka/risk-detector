"""Inférence de production du modèle séquentiel (phase 2 de la feuille de route).

Le gate 2 (§6 sem. 7-8) a évalué le LSTM sur la cohorte de backtest ;
ce module le remet en SERVICE : le job nocturne l'appelle après les
signaux classiques et ajoute le signal `lstm` — la probabilité de faillite
dans les 12 mois, UN SIGNAL PAR EXERCICE (fenêtre glissante) comme les
autres, pour alimenter l'historique et le graphique d'évolution de la fiche.

Règles produit conservées :
  - strict-None : moins de MIN_YEARS exercices datables -> aucun signal ;
    un bilan sans filing_id fait sauter l'exercice concerné (traçabilité
    imposée par test_signals_trace_back_to_filings) ;
  - traçabilité : filing_id = dépôt qui fournit le dernier état de la
    fenêtre (vintage le plus récent du bilan gagnant) ;
  - hors composite : `lstm` n'est pas dans composite.WEIGHTS, il
    s'AFFICHE À CÔTÉ des scores classiques sans les pondérer (règle
    AGENTS.md : un signal DL ne remplace les classiques que s'il les
    bat au backtest — ce n'est pas le cas à det6).

Artefact (data/models/, gitignoré — régénérable par train_lstm) :
  - lstm.pt        state_dict PyTorch (weights_only : sérialisation
                    limitée aux tenseurs, pas de pickle exotique) ;
  - lstm.meta.json seuil de détection (D90 des témoins de validation,
                    ~10 % FPR cible), input_dim, fenêtre MIN/MAX_YEARS,
                    métriques et date d'entraînement.
Absent ou désynchronisé -> le nightly ignore l'inférence (le job reste
vert : le modèle est un bonus, pas un prérequis de la précalculation).
"""

import json
from datetime import date
from pathlib import Path

import torch

from app.db.repo import fetch_event_rows
from app.dl import attribution
from app.dl.dataset import (
    INPUT_DIM,
    MIN_YEARS,
    Sample,
    build_samples,
    company_year_points,
)
from app.dl.model import LstmScorer, predict
from app.signals.common import SEV_ALERT, SEV_OK, SEV_WATCH, SignalResult

MODEL_DIR = Path("data/models")
WEIGHTS_NAME = "lstm.pt"
META_NAME = "lstm.meta.json"
SIGNAL_TYPE = "lstm"  # identifiant produit (DB / API / frontend)

# Cache processuel : le nightly charge le modèle UNE fois pour tout le
# lot ; la clé est le chemin résolu pour que les tests utilisent des
# répertoires temporaires sans se marcher dessus.
_LOADED: dict[str, tuple[LstmScorer, dict]] = {}


def save_artifact(model: LstmScorer, meta: dict, model_dir: Path = MODEL_DIR) -> Path:
    """Écrit l'artefact consommé par load_artifact -> chemin des poids.

    Appelé par scripts/train_lstm à la fin de l'entraînement (le seuil et
    les métriques y sont déjà calculés). Le JSON utilise ensure_ascii pour
    rester lisible partout (pas d'accents prévu de toute façon).
    """
    directory = Path(model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    weights = directory / WEIGHTS_NAME
    torch.save(model.state_dict(), weights)
    (directory / META_NAME).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return weights


def load_artifact(model_dir: Path = MODEL_DIR) -> tuple[LstmScorer, dict] | None:
    """Artefact -> (modèle évalué, meta) ; None si absent ou désynchronisé.

    Désynchronisé = meta.input_dim != INPUT_DIM du code actuel : les
    vecteurs produits par dataset.py ne correspondraient plus au modèle —
    plutôt que de planter au predict, on n'infère pas (ré-entraînement
    requis : uv run python -m scripts.train_lstm).
    """
    key = str(Path(model_dir).resolve())
    if key in _LOADED:
        return _LOADED[key]
    weights = Path(model_dir) / WEIGHTS_NAME
    meta_path = Path(model_dir) / META_NAME
    if not weights.is_file() or not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if int(meta.get("input_dim", -1)) != INPUT_DIM:
        return None
    model = LstmScorer(input_dim=int(meta["input_dim"]))
    state = torch.load(weights, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()  # pas de dropout ici, mais eval() reste la bonne habitude
    _LOADED[key] = (model, meta)
    return _LOADED[key]


def severity_for(prob: float, threshold: float) -> str:
    """Probabilité -> sévérité (bandes provisoires calées sur le seuil).

    - >= seuil   : défaillance — mêmes conditions que l'évaluation du
                   backtest (seuil = D90 des témoins de validation,
                   ~10 % FPR cible, même repère que le gate classique) ;
    - >= seuil/2 : vigilance — mi-chemin, signal précoce (bande
                   rétunable quand l'attribution SHAP sera branchée) ;
    - sinon      : saine.
    """
    if prob >= threshold:
        return SEV_ALERT
    if prob >= threshold / 2:
        return SEV_WATCH
    return SEV_OK


def company_samples(
    rows: list[dict], events: list[dict] | None, cik: int
) -> list[Sample]:
    """Toutes les fenêtres exploitables de l'entreprise, ou [] (strict-None).

    `rows` : lignes DL (CONVENTION dates — period_end et filed_at en
    objet date, cf. infer_company) ; `events` : même forme que
    repo.fetch_event_rows (ISO str).

    strict-None : moins de MIN_YEARS points datables (séquence trop
    courte pour le LSTM) -> []. Chaque échantillon porte sa propre
    disponibilité (max filed_at de SA fenêtre, anti-fuite conservateur).
    """
    points = company_year_points(rows, events)
    if len(points) < MIN_YEARS:
        return []
    # anchor=None : pas de faillite connue ici, les labels valent 0 de
    # toute façon — on ne prédit que des probabilités, on n'évalue pas.
    return build_samples(points, cik, anchor=None)


def _freshest_filings(rows: list[dict]) -> dict:
    """{period_end: (filed_at, filing_id)} — vintage le plus récent par bilan.

    C'est ce dépôt que la fiche affichera comme source de chaque score
    (règle « tout score tracé au dépôt exact »).
    """
    freshest: dict = {}
    for r in rows:
        fid = r.get("filing_id")
        if not fid:
            continue
        key = r["period_end"]
        filed = r.get("filed_at") or date.min
        if key not in freshest or filed > freshest[key][0]:
            freshest[key] = (filed, fid)
    return freshest


def sample_signals(
    rows: list[dict],
    events: list[dict] | None,
    cik: int,
    model: LstmScorer,
    meta: dict,
) -> list[SignalResult]:
    """Lignes DL + dépôts -> un signal `lstm` par exercice exploitable (pur).

    strict-None PAR EXERCICE : un bilan sans filing_id fait sauter son
    signal (jamais un score non traçable) ; < MIN_YEARS points -> [].
    Dérive de features (meta.input_dim != vecteurs) -> [] plutôt crash.
    """
    samples = company_samples(rows, events, cik)
    if not samples:
        return []
    if len(samples[0].sequence[0]) != int(meta["input_dim"]):
        return []
    probs = predict(model, samples)  # mini-batch : une passe pour tout
    freshest = _freshest_filings(rows)
    results: list[SignalResult] = []
    for sample, prob in zip(samples, probs):
        entry = freshest.get(sample.period_end)
        if entry is None:
            continue  # exercice non traçable -> signal omis
        results.append(build_signal(prob, sample, entry[1], meta))
    # Attribution (phase 2 « explication par variable ») : seulement sur
    # le DERNIER score — c'est celui que la fiche présente comme état
    # courant ; l'historique garde des détails légers. Échec de SHAP ->
    # le signal reste affiché sans explication (bonus de lisibilité,
    # jamais un prérequis du score).
    if results:
        try:
            attr = attribution.explain(model, samples[-1])
            results[-1].details["attribution_method"] = "shap_gradient"
            results[-1].details["attribution"] = [
                {"feature": name, "value": round(value, 5)}
                for name, value in attribution.top_contributors(attr)
            ]
        except Exception:
            pass
    return results


def build_signal(
    prob: float, sample: Sample, filing_id: str, meta: dict
) -> SignalResult:
    """Probabilité + échantillon -> SignalResult `lstm` (pur, testable).

    details porte l'audibilité du score (§4 « tout calcul est traçable ») :
    probabilité brute, seuil de référence, provenance de l'artefact et
    taille de fenêtre réellement utilisée (3 à MAX_YEARS).
    """
    return SignalResult(
        signal_type=SIGNAL_TYPE,
        period_end=sample.period_end.isoformat(),
        value=round(prob, 4),
        severity=severity_for(prob, float(meta["threshold"])),
        details={
            "probability": round(prob, 4),
            "threshold": meta["threshold"],
            "model": meta.get("model", "lstm"),
            "trained_at": meta.get("trained_at"),
            "window_years": len(sample.sequence),
            "availability": sample.availability.isoformat(),
        },
        filing_id=filing_id,
    )


def infer_company(
    conn,
    company: dict,
    bundle: tuple[LstmScorer, dict],
) -> list[SignalResult]:
    """Signaux `lstm` d'une entreprise (postgres) — [] si inexploitable.

    `bundle` = sortie de load_artifact (modèle + meta) — chargé une fois
    par le nightly avant la boucle. Requête dédiée (dates + filed_at) :
    les lignes de repo.fetch_fact_rows sont en ISO str et sans filed_at,
    conventions de app.signals.compute, incompatibles avec les points DL.
    """
    model, meta = bundle
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.period_end, f.concept, f.value, f.filing_id, fi.filed_at
            FROM facts f
            LEFT JOIN filings fi ON fi.id = f.filing_id
            WHERE f.company_id = %s
            ORDER BY f.period_end
            """,
            (company["id"],),
        )
        rows = [
            {
                "period_end": r[0],
                "concept": r[1],
                # float() : psycopg renvoie Decimal (même piège qu'ailleurs).
                "value": float(r[2]),
                "filing_id": str(r[3]) if r[3] else None,
                "filed_at": r[4],
            }
            for r in cur.fetchall()
        ]
    # Même contrat None/[] que compute_company : la liste est toujours
    # chargée (on a vérifié, même vide le « 0 » est donc vrai).
    events = fetch_event_rows(conn, company["id"])
    return sample_signals(rows, events, company["cik"], model, meta)
