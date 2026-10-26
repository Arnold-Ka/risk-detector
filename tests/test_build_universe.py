"""Tests purs des filtres du manifeste d'univers SEC, sans accès réseau."""

from scripts.build_universe import candidate_rows, manifest_entry


def test_candidate_rows_keeps_selected_exchanges_and_one_cik():
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [320193, "Apple Inc.", "AAPL", "NYSE"],
            [1411579, "AMC Entertainment", "AMC", "OTC"],
            [1, "Invalid row", "", "NYSE"],
        ],
    }

    rows = candidate_rows(payload)

    assert rows == [
        {"cik": 320193, "name": "Apple Inc.", "ticker": "AAPL", "exchange": "NYSE"}
    ]


def test_manifest_entry_accepts_foreign_annual_forms_and_marks_provenance():
    candidate = {
        "cik": 1114448,
        "name": "Example FPI",
        "ticker": "EXM",
        "exchange": "NYSE",
    }
    submission = {
        "entityType": "other",
        "sic": "2834",
        "filings": {"recent": {"form": ["6-K", "20-F"]}},
    }

    entry = manifest_entry(candidate, submission, "2026-10-27")

    assert entry is not None
    assert entry["annual_forms"] == ["20-F"]
    assert entry["sic"] == "2834"
    assert entry["universe_as_of"] == "2026-10-27"


def test_manifest_entry_excludes_funds_and_candidates_without_annual_reports():
    candidate = {
        "cik": 123,
        "name": "Example fund",
        "ticker": "FND",
        "exchange": "Nasdaq",
    }

    assert manifest_entry(
        candidate,
        {
            "entityType": "investment company",
            "sic": "6726",
            "filings": {"recent": {"form": ["N-CSR"]}},
        },
        "2026-10-27",
    ) is None
    assert manifest_entry(
        candidate,
        {"entityType": "operating", "sic": "7370", "filings": {"recent": {"form": ["8-K"]}}},
        "2026-10-27",
    ) is None
