"""Tests du job nocturne (exige la base levée + données ingérées).

Contrat vérifié :
  1. le job remplit `signals` pour le trio (au moins un signal par type
     attendu, traçabilité filing_id, sévérités dans le vocabulaire) ;
  2. il est idempotent : deux exécutions successives donnent EXACTEMENT
     les mêmes comptes (purge + réinsertion, cf. replace_company_signals) ;
  3. l'unicité (company_id, signal_type, period_end) tient.

Le refresh EDGAR/Yahoo (fetch autonome) est DÉSACTIVÉ ici
(refresh=False) : ces tests ne doivent pas dépendre du réseau. Les
fonctions pures du refresh sont testées dans tests/test_refresh.py.

Si la base est éteinte → skip. Commande :
    docker compose up -d --wait
    uv run python -m scripts.load_postgres   # une fois
    uv run pytest tests/test_nightly.py -v
"""

from collections import Counter

import pytest

from app.db.repo import get_conn
from app.jobs.nightly import main as nightly_main

# Vocabulaire autorisé (les textes affichés, avec accents UTF-8 en base).
SEVERITIES = {"saine", "vigilance", "défaillance"}
LEVELS = {"faible", "modéré", "élevé", "critique"}


def _db_available() -> bool:
    """connect() est paresseux : on exécute SELECT 1 pour forcer l'ouverture."""
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="PostgreSQL indisponible — `docker compose up -d --wait`",
)


def _snapshot() -> tuple[Counter, Counter, list[str]]:
    """(comptes par type, par sévérité, types) de toute la table signals."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT signal_type, severity, count(*) FROM signals "
                        "GROUP BY signal_type, severity")
            rows = cur.fetchall()
    finally:
        conn.close()
    by_type: Counter = Counter()
    by_sev: Counter = Counter()
    for signal_type, severity, n in rows:
        by_type[signal_type] += n
        by_sev[severity] += n
    return by_type, by_sev, sorted(by_type)


def test_nightly_fills_signals_and_is_idempotent():
    # refresh=False : les tests ne doivent PAS frapper EDGAR/Yahoo — le
    # refresh autonome est couvert par test_refresh.py (fonctions pures) ;
    # ici on ne valide que le calcul des signaux sur les données en base.
    nightly_main(refresh=False)  # 1ère exécution
    by_type1, by_sev1, types1 = _snapshot()

    if not types1:
        pytest.skip("table facts vide — lancer scripts.load_postgres d'abord")

    # Tous les types de signaux attendus sont présents sur le trio.
    for expected in ("altman", "piotroski", "runway", "divergence", "composite"):
        assert expected in by_type1, f"type absent: {expected} (reçu: {types1})"
    # Beneish : absent sur AMC (pas de résultat brut) mais présent ailleurs.
    assert by_type1.get("beneish", 0) > 0

    # Sévérités strictement dans le vocabulaire produit.
    assert set(by_sev1) <= (SEVERITIES | LEVELS), set(by_sev1)

    nightly_main(refresh=False)  # 2ème exécution : purge + réinsertion
    by_type2, by_sev2, types2 = _snapshot()
    assert by_type1 == by_type2, "comptes différents après re-exécution"
    assert by_sev1 == by_sev2


def test_nightly_alerts_watchers_on_level_change(monkeypatch):
    """Bout en bout : palier modifié en base -> alerte pour l'abonné, envoi intercepté.

    On falsifie le dernier composite stocké de la première entreprise (celle
    que traite limit=1), on l'ajoute à la liste d'un utilisateur jetable, et
    le nightly doit détecter « palier stocké != palier recalculé ». Le
    recalcul réécrit ensuite le vrai niveau : la base revient à son état.
    """
    from uuid import uuid4

    from app.jobs import nightly

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.ticker, s.severity, s.period_end
                   FROM companies c
                   JOIN signals s ON s.company_id = c.id
                                 AND s.signal_type = 'composite'
                   WHERE c.cik = (SELECT min(cik) FROM companies)
                     AND c.sector_group = 'other'
                   ORDER BY s.period_end DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row is None:
                pytest.skip("aucun composite pour la première entreprise")
            company_id, ticker, real_level, period_end = row
            fake_level = "critique" if real_level != "critique" else "faible"
            cur.execute(
                """UPDATE signals SET severity = %s
                   WHERE company_id = %s AND signal_type = 'composite'
                     AND period_end = %s""",
                (fake_level, company_id, period_end),
            )
            user_id, email = uuid4(), f"alert-test-{uuid4().hex}@example.invalid"
            cur.execute("INSERT INTO users (id, email) VALUES (%s, %s)",
                        (user_id, email))
            cur.execute(
                "INSERT INTO watchlists (user_id, company_id) VALUES (%s, %s)",
                (user_id, company_id),
            )
        conn.commit()

        captured = {}

        def _capture(pending):
            captured.update(pending)
            return {"sent": 0, "failed": 0, "skipped": len(pending)}

        monkeypatch.setattr(nightly, "send_digests", _capture)
        nightly.main(refresh=False, limit=1, notify=True)

        assert email in captured, "l'abonné n'a reçu aucune alerte"
        (change,) = captured[email]
        assert (change.before, change.after) == (fake_level, real_level)
        assert change.ticker == ticker
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM watchlists WHERE user_id IN "
                        "(SELECT id FROM users WHERE email LIKE 'alert-test-%%')")
            cur.execute("DELETE FROM users WHERE email LIKE 'alert-test-%%'")
        conn.commit()
        conn.close()


def test_signals_trace_back_to_filings():
    """Traçabilité : tous les signaux sauf le composite portent un filing_id."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT count(*) FROM signals
                   WHERE signal_type != 'composite' AND filing_id IS NULL"""
            )
            orphans = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM signals")
            total = cur.fetchone()[0]
    finally:
        conn.close()
    if total == 0:
        pytest.skip("signaux non calculés — uv run python -m app.jobs.nightly")
    assert orphans == 0, f"{orphans} signaux sans dépôt source"
