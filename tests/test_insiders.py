# Tests du signal ventes de dirigeants (insiders) + integration compute.
from app.signals.compute import compute_company
from app.signals.insiders import evaluate, is_open_sale

SALE = {
    "code": "S",
    "shares": 10.0,
    "price": 10.0,
    "value": 100.0,
    "owner_name": "Alice",
    "is_officer": True,
    "is_director": False,
    "officer_title": "CFO",
    "filing_id": "f1",
    "transaction_date": "2020-06-01",
    "filed_at": "2020-06-02",
}


def test_is_open_sale_filters():
    assert is_open_sale(SALE)
    assert not is_open_sale({**SALE, "code": "G"})  # don, pas une vente
    assert not is_open_sale({**SALE, "code": "P"})  # achat
    assert not is_open_sale(
        {**SALE, "is_officer": False, "is_director": False, "officer_title": None}
    )  # 10% owner sans fonction : hors perimetre v1
    # Depots anciens : title renseigne sans le flag officier -> compte.
    assert is_open_sale({**SALE, "is_officer": False, "officer_title": "SVP"})


def test_evaluate_saine_when_no_sales():
    res = evaluate([], market_capitalisation=1_000_000.0, shares_outstanding=None,
                   period_end="2020-12-31", filing_id="anchor")
    assert res.severity == "saine" and res.value == 0.0


def test_evaluate_bands_on_market_cap():
    # 3 ventes x 100 $ = 300 $ sur une cap de 100 000 $ -> 0,3 % -> vigilance.
    sales = [{**SALE, "value": 100.0, "shares": 10.0}] * 3
    res = evaluate(sales, 100_000.0, None, "2020-12-31", "anchor")
    assert res.severity == "vigilance"
    assert res.value == 0.003
    assert res.details["n_sales"] == 3
    # 20 ventes x 100 $ = 2 000 $ -> 2 % -> défaillance.
    sales = [{**SALE, "value": 100.0}] * 20
    res = evaluate(sales, 100_000.0, None, "2020-12-31", "anchor")
    assert res.severity == "défaillance" and res.value == 0.02


def test_evaluate_fallback_shares_and_strict_none():
    # Pas de cap -> parts vendues / parts en circulation (tracé).
    sales = [{**SALE, "value": None, "shares": 10_000.0}]
    res = evaluate(sales, None, 1_000_000.0, "2020-12-31", "anchor")
    assert res.value == 0.01 and res.details["denominator"] == "actions_en_circulation"
    # Ni cap ni parts -> strict-None (donnée manquante).
    assert evaluate(sales, None, None, "2020-12-31", "anchor") is None


def test_evaluate_traces_worst_filing():
    sales = [
        {**SALE, "value": 50.0, "filing_id": "small"},
        {**SALE, "value": 900.0, "filing_id": "big"},
    ]
    res = evaluate(sales, 1_000_000.0, None, "2020-12-31", "anchor")
    assert res.filing_id == "big"  # dépôt de la plus grosse vente


def _mini_rows():
    # Exercice 2020 avec tout le necessaire pour cap = price x dei.
    base = {"period_end": "2020-12-31", "filing_id": "k1"}
    return [
        {**base, "concept": "total_assets", "value": 1000.0},
        {**base, "concept": "shares_outstanding", "value": 100.0},
        {**base, "concept": "cash", "value": 100.0},
        {**base, "concept": "sales", "value": 500.0},
    ]


def test_compute_company_wires_insider_signal():
    # cap = cours 10 x 100 parts = 1 000 $ ; vente 5 x 10 $ = 50 $ -> 5 %.
    sale = {**SALE, "shares": 5.0, "price": 10.0, "value": 50.0,
            "transaction_date": "2020-06-01", "filed_at": "2020-06-02"}
    results = compute_company(
        _mini_rows(),
        prices=[("2020-12-30", 10.0)],
        events=[],
        insiders_rows=[sale],
    )
    insider = [r for r in results if r.signal_type == "insider_sales"]
    assert len(insider) == 1
    assert insider[0].severity == "défaillance"
    assert insider[0].value == 0.05
    assert insider[0].details["denominator"] == "capitalisation"
    # Composite de l'exercice inclus (8 composants au max, absent si None).
    compo = [r for r in results if r.signal_type == "composite"]
    assert len(compo) == 1
    assert "insider_sales" in compo[0].details["components"]


def test_compute_company_omits_signal_when_not_loaded():
    # insiders_rows=None -> signal OMIS (pas de « 0 » qui affirmerait
    # avoir vérifié) — même contrat que events.
    results = compute_company(_mini_rows(), prices=[("2020-12-30", 10.0)], events=[])
    assert not [r for r in results if r.signal_type == "insider_sales"]
    compo = [r for r in results if r.signal_type == "composite"][0]
    assert "insider_sales" in compo.details["absent"]
