"""Tests des fonctions pures du refresh nocturne (aucun réseau, aucune base).

select_new_filings et last_closes_for_balances sont le CŒUR de la
détection incrémentale : elles décident de ce qui est ingéré (et donc de
ce qui ne l'est pas — un doublon 4/A ou un cours trop ancien seraient des
vrais bugs produit). Testées ici sans EDGAR ni Yahoo.
"""

from app.ingest.refresh import last_closes_for_balances, select_new_filings

# --- select_new_filings ------------------------------------------------------

RECENT = [
    {"accession": "0000320193-24-000123", "form": "10-K"},   # 0
    {"accession": "0000320193-24-000124", "form": "8-K"},    # 1
    {"accession": "0000320193-24-000125", "form": "4"},      # 2
    {"accession": "0000320193-24-000126", "form": "4/A"},    # 3 — amendement
    {"accession": "0000320193-24-000127", "form": "NT 10-K"},# 4 — retard
]


def test_select_new_filings_filters_by_exact_form():
    # 10-K exact : le 10-K inédit est pris, pas les autres formes.
    out = select_new_filings(RECENT, known=set(), form_of=lambda r: r["form"] == "10-K")
    assert [r["accession"] for r in out] == ["0000320193-24-000123"]


def test_select_new_filings_excludes_amendments_and_known():
    # Form 4 exact : 4/A exclut (re-dépose l'original = doublon).
    out = select_new_filings(RECENT, known=set(), form_of=lambda r: r["form"] == "4")
    assert [r["accession"] for r in out] == ["0000320193-24-000125"]
    # Accession déjà en base : jamais repris.
    out = select_new_filings(
        RECENT, known={"0000320193-24-000125"}, form_of=lambda r: r["form"] == "4"
    )
    assert out == []


def test_select_new_filings_prefix_for_events():
    # 8-K/NT : le préfixe attrape "8-K" ET "NT 10-K" (et les amendements
    # 8-K/A, qui portent les mêmes items — c'est voulu).
    out = select_new_filings(
        RECENT, known=set(), form_of=lambda r: r["form"].startswith(("8-K", "NT"))
    )
    assert [r["form"] for r in out] == ["8-K", "NT 10-K"]


# --- last_closes_for_balances ------------------------------------------------

CLOSES = [
    ("2023-09-28", 170.0),  # veille du bilan Apple FY2023
    ("2023-09-29", 171.0),  # dernier cours ≤ bilan 2023-09-30
    ("2023-10-02", 172.0),  # après le bilan : non retenu
]


def test_last_closes_picks_closest_on_or_before_balance():
    out = last_closes_for_balances(["2023-09-30"], CLOSES, splits=[])
    assert out == [("2023-09-29", 171.0)]


def test_last_closes_deselects_splits():
    # Cours ajusté × facteur des splits postérieurs (Apple 4:1 en 2020) :
    # le 2020-08-28 est multiplié par 4 (les parts XBRL sont brutes).
    closes = [("2020-08-28", 125.0), ("2020-08-31", 129.0)]
    splits = [("2020-08-31", 4.0)]  # split le jour même du dernier cours
    out = last_closes_for_balances(["2020-08-30"], closes, splits)
    # 125.0 × 4 = 500 : le split du 31 n'affecte PAS le cours du 28
    # (strictement après), mais affecterait celui du 31.
    assert out == [("2020-08-28", 500.0)]


def test_last_closes_skips_balance_without_quote():
    # Bilan antérieur à toute cotation : donnée manquante, pas de ligne.
    out = last_closes_for_balances(["1994-09-30"], CLOSES, splits=[])
    assert out == []
